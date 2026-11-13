# Windows-only, derived credential snapshot. This is not a native login store.
param(
    [string]$Action,
    [string]$Provider,
    [string]$StoreDirectory = (Join-Path $PSScriptRoot 'store')
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-StrictMode -Version Latest
$failure = 'Credential operation failed.'
$lock = $null
$stage = $null
$utf8 = [System.Text.UTF8Encoding]::new($false, $true)
$limit = 1048576

function Assert-ProviderId([string]$Id) {
    if ($Id -cnotmatch '\A[a-z][a-z0-9_-]{0,63}\z') { throw 'Invalid provider identifier.' }
}

function Read-Bounded([System.IO.TextReader]$Reader, [int]$Maximum) {
    $buffer = [char[]]::new(4096)
    $result = [System.Text.StringBuilder]::new()
    while (($count = $Reader.Read($buffer, 0, $buffer.Length)) -gt 0) {
        if ($result.Length + $count -gt $Maximum) { throw 'Input exceeds size limit.' }
        [void]$result.Append($buffer, 0, $count)
    }
    return $result.ToString()
}

function Assert-Fields($Object, [string[]]$Names) {
    if ($Object.ValueKind -ne [System.Text.Json.JsonValueKind]::Object) { throw 'Expected an object.' }
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($property in $Object.EnumerateObject()) {
        if ($Names -cnotcontains $property.Name -or -not $seen.Add($property.Name)) { throw 'Unexpected or duplicate field.' }
    }
    if ($seen.Count -ne $Names.Count) { throw 'Missing field.' }
}

function Read-Providers([string]$Json) {
    $document = [System.Text.Json.JsonDocument]::Parse($Json)
    try {
        $root = $document.RootElement
        Assert-Fields $root @('schema_version', 'providers')
        if ($root.GetProperty('schema_version').GetRawText() -cne '1') { throw 'Unsupported schema.' }
        $values = $root.GetProperty('providers')
        if ($values.ValueKind -ne [System.Text.Json.JsonValueKind]::Object) { throw 'Expected provider map.' }
        $map = [System.Collections.Generic.Dictionary[string,string]]::new([System.StringComparer]::Ordinal)
        foreach ($property in $values.EnumerateObject()) {
            Assert-ProviderId $property.Name
            if ($property.Value.ValueKind -ne [System.Text.Json.JsonValueKind]::String) { throw 'Expected a string credential.' }
            $value = $property.Value.GetString()
            if ([string]::IsNullOrWhiteSpace($value) -or $value.Length -gt 65536 -or $value -match '\p{Cc}|[\u2028\u2029]') {
                throw 'Invalid credential text.'
            }
            [void]$utf8.GetByteCount($value) # Reject malformed Unicode, not valid surrogate pairs.
            if (-not $map.TryAdd($property.Name, $value) -or $map.Count -gt 128) { throw 'Invalid provider map.' }
        }
        $canonical = ConvertTo-Json -InputObject @{ schema_version = 1; providers = $map } -Depth 4 -Compress
        if ($utf8.GetByteCount($canonical) -gt $limit) { throw 'Credential snapshot exceeds size limit.' }
        return ,$map
    } finally { $document.Dispose() }
}

function Assert-Path([string]$Path) {
    # Check every existing component, including ancestors outside the private store.
    $current = $Path
    while ($current) {
        try {
            $attributes = [System.IO.File]::GetAttributes($current)
            if (($attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse paths are not supported.' }
        } catch [System.IO.FileNotFoundException] {
        } catch [System.IO.DirectoryNotFoundException] {
        }
        $current = [System.IO.Path]::GetDirectoryName($current)
    }
}

function New-PrivateAcl([bool]$Directory) {
    if ($Directory) { $acl = [System.Security.AccessControl.DirectorySecurity]::new() }
    else { $acl = [System.Security.AccessControl.FileSecurity]::new() }
    $acl.SetOwner($userSid)
    $acl.SetAccessRuleProtection($true, $false)
    $inherit = [System.Security.AccessControl.InheritanceFlags]::None
    if ($Directory) { $inherit = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit' }
    foreach ($sid in @($userSid, $systemSid)) {
        $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
            $sid, [System.Security.AccessControl.FileSystemRights]::FullControl,
            $inherit, [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow))
    }
    return $acl
}

function Assert-Private([string]$Path, [bool]$Directory) {
    Assert-Path $Path
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer -ne $Directory) { throw 'Unexpected path type.' }
    $acl = Get-Acl -LiteralPath $Path
    if ($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $userSid.Value -or -not $acl.AreAccessRulesProtected) {
        throw 'Unexpected owner or inherited permissions.'
    }
    $seen = [System.Collections.Generic.HashSet[string]]::new()
    $inherit = [System.Security.AccessControl.InheritanceFlags]::None
    if ($Directory) { $inherit = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit' }
    foreach ($rule in $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])) {
        $sid = $rule.IdentityReference.Value
        if ($sid -notin @($userSid.Value, $systemSid.Value) -or $rule.IsInherited -or
            $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            $rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl -or
            $rule.InheritanceFlags -ne $inherit -or
            $rule.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None) {
            throw 'Unexpected permissions.'
        }
        [void]$seen.Add($sid)
    }
    if ($seen.Count -ne 2) { throw 'Missing private permissions.' }
}

function New-PrivateFile([string]$Path) {
    return [System.IO.FileSystemAclExtensions]::Create(
        [System.IO.FileInfo]::new($Path), [System.IO.FileMode]::CreateNew,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.IO.FileShare]::None, 4096, [System.IO.FileOptions]::None, (New-PrivateAcl $false))
}

function Read-Snapshot {
    Assert-Private $snapshotPath $false
    # Readers permit atomic replacement; they see either complete snapshot.
    $stream = [System.IO.FileStream]::new($snapshotPath, [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read, [System.IO.FileShare]'ReadWrite, Delete')
    $reader = [System.IO.StreamReader]::new($stream, $utf8)
    try { $json = Read-Bounded $reader (2 * $limit) } finally { $reader.Dispose() }
    $document = [System.Text.Json.JsonDocument]::Parse($json)
    try {
        $root = $document.RootElement
        Assert-Fields $root @('marker', 'schema_version', 'protection', 'payload')
        if ($root.GetProperty('marker').GetString() -cne 'llm-credentials' -or
            $root.GetProperty('schema_version').GetRawText() -cne '1' -or
            $root.GetProperty('protection').GetString() -cne 'DPAPI-CurrentUser') { throw 'Unrecognized store.' }
        $encrypted = [Convert]::FromBase64String($root.GetProperty('payload').GetString())
        $plain = [System.Security.Cryptography.ProtectedData]::Unprotect(
            $encrypted, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
        try { return ,(Read-Providers $utf8.GetString($plain)) }
        finally { [Array]::Clear($plain, 0, $plain.Length) }
    } finally { $document.Dispose() }
}

try {
    $failure = 'Credential request is invalid.'
    if (-not $IsWindows -or $Action -cnotin @('Publish', 'Get') -or $args.Count -ne 0) { throw 'Unsupported request.' }
    if ($Action -ceq 'Get') { Assert-ProviderId $Provider }
    elseif ($Provider) { throw 'Publish does not accept a provider.' }
    if ($Action -ceq 'Publish') {
        # Pipes are UTF-8 bytes regardless of the console's current code page.
        $inputReader = [System.IO.StreamReader]::new([Console]::OpenStandardInput(), $utf8, $false)
        try { $providers = Read-Providers (Read-Bounded $inputReader $limit) }
        finally { $inputReader.Dispose() }
    }

    $failure = 'Credential store path or permissions are unsafe.'
    $userSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $systemSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18')
    $store = [System.IO.Path]::GetFullPath($StoreDirectory).TrimEnd('\', '/')
    if ($store -notmatch '^[a-zA-Z]:[\\/]' -or $store.Substring(2) -match ':|[. ]([\\/]|$)') { throw 'Unsupported store path.' }
    Assert-Path $store
    $snapshotPath = Join-Path $store 'snapshot.json'
    $lockPath = Join-Path $store 'publish.lock'
    if ([System.IO.Directory]::Exists($store)) { Assert-Private $store $true }
    elseif ($Action -ceq 'Get') { throw 'Missing store.' }
    else {
        # Only the derived store is private; never alter ACLs on shared parents.
        [void][System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($store))
        Assert-Path $store
        [System.IO.FileSystemAclExtensions]::Create([System.IO.DirectoryInfo]::new($store), (New-PrivateAcl $true))
        Assert-Private $store $true
    }

    if ($Action -ceq 'Get') {
        $failure = 'Credential snapshot is missing, invalid, or inaccessible.'
        $providers = Read-Snapshot
        $failure = 'Credential provider is not available.'
        if (-not $providers.ContainsKey($Provider)) { throw 'Missing provider.' }
        $outputBytes = $utf8.GetBytes($providers[$Provider])
        $outputStream = [Console]::OpenStandardOutput()
        try {
            $outputStream.Write($outputBytes, 0, $outputBytes.Length)
            $outputStream.Flush()
        } finally {
            [Array]::Clear($outputBytes, 0, $outputBytes.Length)
            $outputStream.Dispose()
        }
    } else {
        $failure = 'Credential store contains unexpected files or permissions.'
        # An absent lock is legitimate only for an empty initial directory.
        # Check lock existence AFTER enumeration: another initial publisher may
        # have just created it. With a lock present, inspect entries only after
        # acquiring it so another publisher's live staging file is not rejected.
        $entries = [System.IO.Directory]::GetFileSystemEntries($store)
        if (-not [System.IO.File]::Exists($lockPath) -and $entries.Length -ne 0) {
            throw 'Refusing to adopt an orphaned or foreign store.'
        }
        $failure = 'Credential publisher lock is unsafe or busy (5 second timeout).'
        $timer = [System.Diagnostics.Stopwatch]::StartNew()
        while ($null -eq $lock) {
            Assert-Private $store $true
            Assert-Path $lockPath
            try {
                if ([System.IO.File]::Exists($lockPath)) {
                    Assert-Private $lockPath $false
                    $lock = [System.IO.FileStream]::new($lockPath, [System.IO.FileMode]::Open,
                        [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
                } else {
                    $lock = New-PrivateFile $lockPath
                    $bytes = $utf8.GetBytes('llm-credentials-lock-v1')
                    $lock.Write($bytes, 0, $bytes.Length)
                    $lock.Flush($true)
                    $lock.Position = 0
                }
            } catch [System.IO.IOException] {
                if ($timer.ElapsedMilliseconds -ge 5000) { throw 'Publisher lock timeout.' }
                Start-Sleep -Milliseconds 50
            }
        }
        $bytes = [byte[]]::new(23)
        if ($lock.Length -ne 23 -or $lock.Read($bytes, 0, 23) -ne 23 -or $utf8.GetString($bytes) -cne 'llm-credentials-lock-v1') {
            throw 'Unrecognized lock.'
        }
        $failure = 'Credential store contains unexpected files or permissions.'
        foreach ($entry in [System.IO.Directory]::GetFileSystemEntries($store)) {
            if ([System.IO.Path]::GetFileName($entry) -cnotin @('publish.lock', 'snapshot.json')) { throw 'Unrecognized store entry.' }
            Assert-Private $entry $false
        }
        $same = $false
        if ([System.IO.File]::Exists($snapshotPath)) {
            $failure = 'Existing credential snapshot is invalid; refusing to replace it.'
            $previous = Read-Snapshot
            $same = $previous.Count -eq $providers.Count
            foreach ($id in $providers.Keys) {
                if (-not $previous.ContainsKey($id) -or -not [StringComparer]::Ordinal.Equals($previous[$id], $providers[$id])) { $same = $false; break }
            }
        }
        if (-not $same) {
            $failure = 'Credential snapshot could not be protected or atomically published.'
            $plain = $utf8.GetBytes((ConvertTo-Json -InputObject @{ schema_version = 1; providers = $providers } -Depth 4 -Compress))
            try {
                $encrypted = [System.Security.Cryptography.ProtectedData]::Protect(
                    $plain, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
            } finally { [Array]::Clear($plain, 0, $plain.Length) }
            $outer = ConvertTo-Json -InputObject ([ordered]@{
                marker = 'llm-credentials'; schema_version = 1; protection = 'DPAPI-CurrentUser'
                payload = [Convert]::ToBase64String($encrypted)
            }) -Compress
            $stage = Join-Path $store ('.snapshot.' + [Guid]::NewGuid().ToString('N') + '.tmp')
            $file = New-PrivateFile $stage
            try {
                $bytes = $utf8.GetBytes($outer)
                $file.Write($bytes, 0, $bytes.Length)
                $file.Flush($true)
            } finally { $file.Dispose() }
            Assert-Private $stage $false
            Assert-Private $store $true
            if ([System.IO.File]::Exists($snapshotPath)) { [System.IO.File]::Replace($stage, $snapshotPath, [NullString]::Value) }
            else { [System.IO.File]::Move($stage, $snapshotPath) }
            $stage = $null
        }
    }
} catch {
    # Never format exceptions: JSON/DPAPI/PowerShell errors can contain credentials.
    [Console]::Error.WriteLine($failure)
    exit 1
} finally {
    if ($stage) { try { [System.IO.File]::Delete($stage) } catch {} }
    if ($null -ne $lock) { $lock.Dispose() }
}
