param(
    [Parameter(Mandatory)]
    [string]$RenderedScript
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:AssertionCount = 0

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    $script:AssertionCount++
    if (-not $Condition) {
        throw "Assertion failed: $Message"
    }
}

function Assert-Null {
    param(
        [AllowNull()]
        $Value,
        [string]$Message
    )

    $script:AssertionCount++
    if ($null -ne $Value) {
        throw "Assertion failed: $Message"
    }
}

function Assert-Throws {
    param(
        [scriptblock]$Action,
        [string]$Like,
        [string]$Message
    )

    $script:AssertionCount++
    try {
        & $Action
    }
    catch {
        if ($_.Exception.Message -notlike $Like) {
            throw "Assertion failed: $Message (expected '$Like', got '$($_.Exception.Message)')"
        }
        return
    }

    throw "Assertion failed: $Message (no error was thrown)"
}

function Write-ValidManifests {
    param([string]$Central)

    New-Item -ItemType Directory -Force `
        (Join-Path $Central '.codex-plugin'), `
        (Join-Path $Central '.claude-plugin') | Out-Null
    '{"name":"superpowers"}' | Set-Content -NoNewline (Join-Path $Central '.codex-plugin/plugin.json')
    '{"name":"superpowers"}' | Set-Content -NoNewline (Join-Path $Central '.claude-plugin/plugin.json')
}

function Write-MattManifest {
    param(
        [string]$Root,
        [object[]]$SkillPaths = @('skills/engineering/matt-only'),
        [string]$Name = 'mattpocock-skills',
        [switch]$CreateSkills
    )

    New-Item -ItemType Directory -Force (Join-Path $Root '.claude-plugin') | Out-Null
    if ($CreateSkills) {
        foreach ($skillPath in $SkillPaths) {
            if ($skillPath -isnot [string]) { continue }
            $relativePath = $skillPath
            if ($relativePath.StartsWith('./', [StringComparison]::Ordinal)) {
                $relativePath = $relativePath.Substring(2)
            }
            if ($relativePath -notmatch '(^|/)\.\.?(?:/|$)' -and -not [IO.Path]::IsPathFullyQualified($relativePath)) {
                $skillRoot = Join-Path $Root $relativePath
                New-Item -ItemType Directory -Force $skillRoot | Out-Null
                '# matt fixture' | Set-Content -NoNewline (Join-Path $skillRoot 'SKILL.md')
            }
        }
    }

    [ordered]@{
        name = $Name
        skills = @($SkillPaths)
    } | ConvertTo-Json -Depth 4 | Set-Content -NoNewline (
        Join-Path $Root '.claude-plugin/plugin.json'
    )
}

function New-MattFixture {
    param(
        [string]$Root,
        [object[]]$SkillPaths = @('./skills/engineering/matt-only')
    )

    New-Item -ItemType Directory -Force $Root | Out-Null
    Write-MattManifest -Root $Root -SkillPaths $SkillPaths -CreateSkills
    return $Root
}

function Add-MutationSentinels {
    param(
        [string]$Central,
        [string]$Shared
    )

    $staleTarget = Join-Path $Central 'skills/stale-owned'
    New-Item -ItemType Directory -Force $staleTarget | Out-Null
    New-DirectoryLink -Path (Join-Path $Shared 'stale-owned') -Target $staleTarget
    Remove-Item -LiteralPath $staleTarget -Recurse -Force
}

function Assert-MutationSentinelsUntouched {
    param(
        [string]$Shared,
        [string]$DesiredName = 'superpower-only'
    )

    Assert-True (
        $null -ne (Get-LinkItem (Join-Path $Shared 'stale-owned'))
    ) 'preflight failure preserves an owned stale link'
    Assert-Null (
        (Get-LinkItem (Join-Path $Shared $DesiredName))
    ) 'preflight failure creates no desired link'
}

function New-Skill {
    param(
        [string]$Central,
        [string]$Name
    )

    $skill = Join-Path $Central "skills/$Name"
    New-Item -ItemType Directory -Force $skill | Out-Null
    "# $Name" | Set-Content -NoNewline (Join-Path $skill 'SKILL.md')
    return $skill
}

function New-Fixture {
    param(
        [string]$TestRoot,
        [string]$Name
    )

    $root = Join-Path $TestRoot $Name
    $central = Join-Path $root 'central'
    $shared = Join-Path $root '.agents/skills'
    New-Item -ItemType Directory -Force $central, $shared | Out-Null
    Write-ValidManifests -Central $central
    return [pscustomobject]@{
        Central = $central
        Shared = $shared
    }
}

function New-DirectoryLink {
    param(
        [string]$Path,
        [string]$Target
    )

    New-Item -ItemType SymbolicLink -Path $Path -Target $Target | Out-Null
}

function Get-LinkItem {
    param([string]$Path)

    return Get-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
}

function Invoke-Reconciler {
    param(
        [string]$Central,
        [string]$Shared,
        [string]$Matt = (Join-Path (Split-Path $Central -Parent) 'matt')
    )

    if (-not (Test-Path -LiteralPath $Matt)) {
        New-MattFixture -Root $Matt | Out-Null
    }
    & $RenderedScript `
        -SuperpowersRoot $Central `
        -MattpocockSkillsRoot $Matt `
        -SharedSkillsRoot $Shared | Out-Null
}

$testRoot = Join-Path ([IO.Path]::GetTempPath()) ("superpowers-links-" + [guid]::NewGuid())
try {
    $central = Join-Path $testRoot 'central'
    $shared = Join-Path $testRoot '.agents/skills'
    New-Item -ItemType Directory -Force `
        "$central/.codex-plugin", `
        "$central/.claude-plugin", `
        $shared | Out-Null
    '{"name":"superpowers"}' | Set-Content -NoNewline "$central/.codex-plugin/plugin.json"
    '{"name":"superpowers"}' | Set-Content -NoNewline "$central/.claude-plugin/plugin.json"

    $driveRoot = [IO.Path]::GetPathRoot($testRoot)
    $tokens = $null
    $parseErrors = $null
    $renderedAst = [Management.Automation.Language.Parser]::ParseFile(
        $RenderedScript,
        [ref]$tokens,
        [ref]$parseErrors
    )
    if ($parseErrors.Count -ne 0) {
        throw "Rendered reconciler failed to parse: $($parseErrors[0].Message)"
    }
    $normalizeFunction = $renderedAst.Find({
        param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq 'Normalize-AbsolutePath'
    }, $true)
    if ($null -eq $normalizeFunction) {
        throw 'Rendered reconciler does not define Normalize-AbsolutePath.'
    }
    Invoke-Expression $normalizeFunction.Extent.Text
    Assert-True (
        (Normalize-AbsolutePath $driveRoot $testRoot) -eq $driveRoot
    ) 'absolute path normalization preserves the current drive root'

    $brainstorming = New-Skill -Central $central -Name 'brainstorming'
    New-Item -ItemType Directory -Force "$central/skills/no-skill", "$central/skills/container/nested" | Out-Null
    '# nested' | Set-Content -NoNewline "$central/skills/container/nested/SKILL.md"

    $legacyTarget = Join-Path $testRoot 'legacy-agent-cache/unrelated'
    New-Item -ItemType Directory -Force $legacyTarget | Out-Null
    $unrelatedPath = Join-Path $shared 'unrelated'
    New-DirectoryLink -Path $unrelatedPath -Target $legacyTarget

    $unrelatedFilePath = Join-Path $shared 'unrelated-file'
    $unrelatedDirectoryPath = Join-Path $shared 'unrelated-directory'
    'unrelated' | Set-Content -NoNewline $unrelatedFilePath
    New-Item -ItemType Directory -Force $unrelatedDirectoryPath | Out-Null

    Invoke-Reconciler -Central $central -Shared $shared

    $defaultMattTarget = Join-Path $testRoot 'matt/skills/engineering/matt-only'
    $defaultMattLink = Get-LinkItem (Join-Path $shared 'matt-only')
    Assert-True ($null -ne $defaultMattLink) 'a manifest-selected nested Matt skill is linked'
    Assert-True ($defaultMattLink.LinkType -eq 'SymbolicLink') 'the Matt skill link is symbolic'
    Assert-True (
        [IO.Path]::GetFullPath([string]$defaultMattLink.LinkTarget) -eq
            [IO.Path]::GetFullPath($defaultMattTarget)
    ) 'the Matt skill link targets the declared nested directory'
    Assert-True (Test-Path -LiteralPath $unrelatedFilePath -PathType Leaf) 'an unrelated plain file remains untouched'
    Assert-True (Test-Path -LiteralPath $unrelatedDirectoryPath -PathType Container) 'an unrelated directory remains untouched'

    $brainstormingLink = Get-LinkItem "$shared/brainstorming"
    Assert-True ($null -ne $brainstormingLink) 'a direct child skill is linked'
    Assert-True ($brainstormingLink.LinkType -eq 'SymbolicLink') 'the skill link is symbolic'
    Assert-True ([bool]$brainstormingLink.PSIsContainer) 'the skill link is a directory link'
    Assert-True ([IO.Path]::IsPathFullyQualified([string]$brainstormingLink.LinkTarget)) 'the stored target is absolute'
    Assert-True (
        [IO.Path]::GetFullPath([string]$brainstormingLink.LinkTarget) -eq [IO.Path]::GetFullPath($brainstorming)
    ) 'the skill link targets the central direct child'
    Assert-True (Test-Path -LiteralPath "$shared/brainstorming/SKILL.md" -PathType Leaf) 'SKILL.md is reachable through the link'
    Assert-Null (Get-LinkItem "$shared/no-skill") 'a direct child without SKILL.md is ignored'
    Assert-Null (Get-LinkItem "$shared/container") 'a parent of a nested skill is ignored'
    Assert-Null (Get-LinkItem "$shared/nested") 'a nested skill is not linked as a direct child'
    Assert-True (
        [IO.Path]::GetFullPath([string](Get-LinkItem $unrelatedPath).LinkTarget) -eq [IO.Path]::GetFullPath($legacyTarget)
    ) 'an unrelated differently named link remains untouched'

    Invoke-Reconciler -Central $central -Shared $shared
    $rerunLink = Get-LinkItem "$shared/brainstorming"
    Assert-True ($null -ne $rerunLink) 'an idempotent rerun keeps the desired link'
    Assert-True (
        [IO.Path]::GetFullPath([string]$rerunLink.LinkTarget) -eq [IO.Path]::GetFullPath($brainstorming)
    ) 'an idempotent rerun preserves the desired target'
    Assert-True ($null -ne (Get-LinkItem $unrelatedPath)) 'an idempotent rerun still preserves unrelated links'

    $deprecated = New-Skill -Central $central -Name 'deprecated'
    Invoke-Reconciler -Central $central -Shared $shared
    Assert-True ($null -ne (Get-LinkItem "$shared/deprecated")) 'a newly current skill is linked'
    Remove-Item -LiteralPath $deprecated -Recurse -Force
    Invoke-Reconciler -Central $central -Shared $shared
    Assert-Null (
        (Get-Item -LiteralPath "$shared/deprecated" -Force -ErrorAction SilentlyContinue)
    ) 'a removed central skill leaves no broken shared link'

    $collisionFixture = New-Fixture -TestRoot $testRoot -Name 'collision'
    New-Skill -Central $collisionFixture.Central -Name 'alpha' | Out-Null
    New-Skill -Central $collisionFixture.Central -Name 'beta' | Out-Null
    $staleTarget = Join-Path $collisionFixture.Central 'skills/stale'
    New-Item -ItemType Directory -Force $staleTarget | Out-Null
    New-DirectoryLink -Path (Join-Path $collisionFixture.Shared 'stale') -Target $staleTarget
    Remove-Item -LiteralPath $staleTarget -Recurse -Force
    $legacyCollisionTarget = Join-Path $testRoot 'legacy-agent-cache/brainstorming'
    New-Item -ItemType Directory -Force $legacyCollisionTarget | Out-Null
    New-DirectoryLink -Path (Join-Path $collisionFixture.Shared 'alpha') -Target $legacyCollisionTarget

    Assert-Throws {
        Invoke-Reconciler -Central $collisionFixture.Central -Shared $collisionFixture.Shared
    } '*non-owned collision*' 'a legacy same-name link blocks reconciliation'
    Assert-True ($null -ne (Get-LinkItem (Join-Path $collisionFixture.Shared 'stale'))) 'collision preflight does not remove an owned stale link'
    Assert-Null (Get-LinkItem (Join-Path $collisionFixture.Shared 'beta')) 'collision preflight creates no other desired links'
    Assert-True (
        [IO.Path]::GetFullPath([string](Get-LinkItem (Join-Path $collisionFixture.Shared 'alpha')).LinkTarget) -eq
            [IO.Path]::GetFullPath($legacyCollisionTarget)
    ) 'collision preflight leaves the non-owned link untouched'

    $relativeCollisionFixture = New-Fixture -TestRoot $testRoot -Name 'relative-collision'
    New-Skill -Central $relativeCollisionFixture.Central -Name 'alpha' | Out-Null
    New-Skill -Central $relativeCollisionFixture.Central -Name 'beta' | Out-Null
    $relativeStaleTarget = Join-Path $relativeCollisionFixture.Central 'skills/stale'
    New-Item -ItemType Directory -Force $relativeStaleTarget | Out-Null
    New-DirectoryLink -Path (Join-Path $relativeCollisionFixture.Shared 'stale') -Target $relativeStaleTarget
    Remove-Item -LiteralPath $relativeStaleTarget -Recurse -Force
    $relativeTarget = '../../central/skills/alpha'
    $relativeCollisionLink = Join-Path $relativeCollisionFixture.Shared 'alpha'
    [IO.Directory]::CreateSymbolicLink($relativeCollisionLink, $relativeTarget) | Out-Null

    Assert-Throws {
        Invoke-Reconciler -Central $relativeCollisionFixture.Central -Shared $relativeCollisionFixture.Shared
    } '*non-owned collision*' 'a same-name relative link into central skills is non-owned'
    Assert-True ($null -ne (Get-LinkItem (Join-Path $relativeCollisionFixture.Shared 'stale'))) 'relative collision preflight does not remove an owned stale link'
    Assert-Null (Get-LinkItem (Join-Path $relativeCollisionFixture.Shared 'beta')) 'relative collision preflight creates no other desired links'
    $relativeCollisionItem = Get-LinkItem $relativeCollisionLink
    Assert-True ($null -ne $relativeCollisionItem) 'relative collision preflight leaves the colliding link in place'
    Assert-True (
        [string]$relativeCollisionItem.LinkTarget -eq $relativeTarget
    ) 'relative collision preflight preserves the stored relative target'

    $relativeUnrelatedFixture = New-Fixture -TestRoot $testRoot -Name 'relative-unrelated'
    New-Skill -Central $relativeUnrelatedFixture.Central -Name 'alpha' | Out-Null
    $relativeUnrelatedTarget = '../../central/skills/alpha'
    $relativeUnrelatedLink = Join-Path $relativeUnrelatedFixture.Shared 'legacy-relative'
    [IO.Directory]::CreateSymbolicLink($relativeUnrelatedLink, $relativeUnrelatedTarget) | Out-Null

    Invoke-Reconciler -Central $relativeUnrelatedFixture.Central -Shared $relativeUnrelatedFixture.Shared
    $relativeUnrelatedItem = Get-LinkItem $relativeUnrelatedLink
    Assert-True ($null -ne $relativeUnrelatedItem) 'a differently named relative link into central skills remains untouched'
    Assert-True (
        [string]$relativeUnrelatedItem.LinkTarget -eq $relativeUnrelatedTarget
    ) 'a differently named relative link preserves its stored target'

    $invalidTargetFixture = New-Fixture -TestRoot $testRoot -Name 'invalid-link-target'
    New-Skill -Central $invalidTargetFixture.Central -Name 'desired' | Out-Null
    $ownedTarget = Join-Path $invalidTargetFixture.Central 'skills/old-owned'
    New-Item -ItemType Directory -Force $ownedTarget | Out-Null
    New-DirectoryLink -Path (Join-Path $invalidTargetFixture.Shared 'old-owned') -Target $ownedTarget
    Remove-Item -LiteralPath $ownedTarget -Recurse -Force
    $invalidLink = Join-Path $invalidTargetFixture.Shared 'invalid-target'
    [IO.Directory]::CreateSymbolicLink($invalidLink, ' ') | Out-Null

    Assert-Throws {
        Invoke-Reconciler -Central $invalidTargetFixture.Central -Shared $invalidTargetFixture.Shared
    } '*LinkTarget*' 'an invalid stored LinkTarget aborts reconciliation'
    Assert-True ($null -ne (Get-LinkItem (Join-Path $invalidTargetFixture.Shared 'old-owned'))) 'invalid target preflight does not remove an owned stale link'
    Assert-Null (Get-LinkItem (Join-Path $invalidTargetFixture.Shared 'desired')) 'invalid target preflight creates no desired link'
    Assert-True ($null -ne (Get-LinkItem $invalidLink)) 'invalid target preflight leaves the offending link untouched'

    foreach ($manifestRelativePath in @('.codex-plugin/plugin.json', '.claude-plugin/plugin.json')) {
        foreach ($case in @('missing', 'malformed', 'wrong-name')) {
            $fixtureName = 'manifest-' + ($manifestRelativePath -replace '[^a-z]', '-') + '-' + $case
            $manifestFixture = New-Fixture -TestRoot $testRoot -Name $fixtureName
            New-Skill -Central $manifestFixture.Central -Name 'desired' | Out-Null
            $manifestStaleTarget = Join-Path $manifestFixture.Central 'skills/stale-owned'
            New-Item -ItemType Directory -Force $manifestStaleTarget | Out-Null
            New-DirectoryLink -Path (Join-Path $manifestFixture.Shared 'stale-owned') -Target $manifestStaleTarget
            Remove-Item -LiteralPath $manifestStaleTarget -Recurse -Force

            $manifestPath = Join-Path $manifestFixture.Central $manifestRelativePath
            switch ($case) {
                'missing' { Remove-Item -LiteralPath $manifestPath -Force }
                'malformed' { '{not-json' | Set-Content -NoNewline $manifestPath }
                'wrong-name' { '{"name":"something-else"}' | Set-Content -NoNewline $manifestPath }
            }

            Assert-Throws {
                Invoke-Reconciler -Central $manifestFixture.Central -Shared $manifestFixture.Shared
            } '*manifest*superpowers*' "$case $manifestRelativePath fails manifest preflight"
            Assert-True (
                $null -ne (Get-LinkItem (Join-Path $manifestFixture.Shared 'stale-owned'))
            ) "$case $manifestRelativePath does not remove existing owned links"
            Assert-Null (
                (Get-LinkItem (Join-Path $manifestFixture.Shared 'desired'))
            ) "$case $manifestRelativePath creates no desired link"
        }
    }

    $mattHappy = New-Fixture -TestRoot $testRoot -Name 'matt-happy'
    New-Skill -Central $mattHappy.Central -Name 'superpower-only' | Out-Null
    $mattHappyRoot = Join-Path $testRoot 'matt-happy/matt-custom'
    New-MattFixture -Root $mattHappyRoot -SkillPaths @(
        './skills/engineering/tdd',
        './skills/productivity/teach',
        './skills/engineering/deprecated'
    ) | Out-Null
    Invoke-Reconciler -Central $mattHappy.Central -Matt $mattHappyRoot -Shared $mattHappy.Shared
    Assert-True (Test-Path -LiteralPath (Join-Path $mattHappy.Shared 'tdd/SKILL.md')) 'Matt engineering skill is reachable'
    Assert-True (Test-Path -LiteralPath (Join-Path $mattHappy.Shared 'teach/SKILL.md')) 'Matt productivity skill is reachable'
    Assert-True ($null -ne (Get-LinkItem (Join-Path $mattHappy.Shared 'deprecated'))) 'current Matt skill is linked before deprecation'

    Remove-Item -LiteralPath (Join-Path $mattHappyRoot 'skills/engineering/deprecated') -Recurse -Force
    Write-MattManifest -Root $mattHappyRoot -SkillPaths @(
        './skills/engineering/tdd',
        './skills/productivity/teach'
    )
    Invoke-Reconciler -Central $mattHappy.Central -Matt $mattHappyRoot -Shared $mattHappy.Shared
    Assert-Null (Get-LinkItem (Join-Path $mattHappy.Shared 'deprecated')) 'deprecated Matt link is removed from its stored target'

    foreach ($unsafePath in @(
        '../outside',
        './skills/../outside',
        './skills//empty',
        './skills/./dot',
        'skills\foo\..\bar',
        'skills\foo\.\bar',
        'skills\foo\\bar',
        'docs/not-a-skill',
        ([IO.Path]::GetFullPath((Join-Path $testRoot 'absolute-skill')))
    )) {
        $safeName = [Convert]::ToHexString(
            [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($unsafePath))
        ).Substring(0, 16)
        $unsafeFixture = New-Fixture -TestRoot $testRoot -Name "matt-unsafe-$safeName"
        New-Skill -Central $unsafeFixture.Central -Name 'superpower-only' | Out-Null
        $unsafeMatt = Join-Path $testRoot "matt-unsafe-$safeName/matt"
        New-Item -ItemType Directory -Force $unsafeMatt | Out-Null
        Write-MattManifest -Root $unsafeMatt -SkillPaths @($unsafePath)
        Add-MutationSentinels -Central $unsafeFixture.Central -Shared $unsafeFixture.Shared

        Assert-Throws {
            Invoke-Reconciler -Central $unsafeFixture.Central -Matt $unsafeMatt -Shared $unsafeFixture.Shared
        } '*Matt*skill path*' "unsafe Matt path '$unsafePath' fails preflight"
        Assert-MutationSentinelsUntouched -Shared $unsafeFixture.Shared
    }

    $missingSkillFixture = New-Fixture -TestRoot $testRoot -Name 'matt-missing-skill'
    New-Skill -Central $missingSkillFixture.Central -Name 'superpower-only' | Out-Null
    $missingSkillMatt = Join-Path $testRoot 'matt-missing-skill/matt'
    New-Item -ItemType Directory -Force $missingSkillMatt | Out-Null
    Write-MattManifest -Root $missingSkillMatt -SkillPaths @('./skills/engineering/missing')
    Add-MutationSentinels -Central $missingSkillFixture.Central -Shared $missingSkillFixture.Shared
    Assert-Throws {
        Invoke-Reconciler -Central $missingSkillFixture.Central -Matt $missingSkillMatt -Shared $missingSkillFixture.Shared
    } '*SKILL.md*' 'a declared Matt path without SKILL.md fails preflight'
    Assert-MutationSentinelsUntouched -Shared $missingSkillFixture.Shared

    $reparseFixture = New-Fixture -TestRoot $testRoot -Name 'matt-reparse-component'
    New-Skill -Central $reparseFixture.Central -Name 'superpower-only' | Out-Null
    $reparseMatt = Join-Path $testRoot 'matt-reparse-component/matt'
    $outsideSkill = Join-Path $testRoot 'matt-reparse-component/outside/escaped'
    New-Item -ItemType Directory -Force `
        (Join-Path $reparseMatt 'skills'), `
        $outsideSkill | Out-Null
    '# escaped fixture' | Set-Content -NoNewline (Join-Path $outsideSkill 'SKILL.md')
    New-DirectoryLink `
        -Path (Join-Path $reparseMatt 'skills/linked-outside') `
        -Target (Split-Path $outsideSkill -Parent)
    Write-MattManifest `
        -Root $reparseMatt `
        -SkillPaths @('./skills/linked-outside/escaped')
    Add-MutationSentinels -Central $reparseFixture.Central -Shared $reparseFixture.Shared

    Assert-Throws {
        Invoke-Reconciler -Central $reparseFixture.Central -Matt $reparseMatt -Shared $reparseFixture.Shared
    } '*Matt*skill path*reparse point*' 'an intermediate reparse point in a Matt path fails preflight'
    Assert-MutationSentinelsUntouched -Shared $reparseFixture.Shared

    $duplicateFixture = New-Fixture -TestRoot $testRoot -Name 'matt-duplicate-basename'
    New-Skill -Central $duplicateFixture.Central -Name 'superpower-only' | Out-Null
    $duplicateMatt = Join-Path $testRoot 'matt-duplicate-basename/matt'
    New-MattFixture -Root $duplicateMatt -SkillPaths @(
        './skills/engineering/tdd',
        './skills/productivity/tdd'
    ) | Out-Null
    Add-MutationSentinels -Central $duplicateFixture.Central -Shared $duplicateFixture.Shared
    Assert-Throws {
        Invoke-Reconciler -Central $duplicateFixture.Central -Matt $duplicateMatt -Shared $duplicateFixture.Shared
    } '*duplicate*name*tdd*' 'duplicate Matt basenames fail preflight'
    Assert-MutationSentinelsUntouched -Shared $duplicateFixture.Shared

    $crossFixture = New-Fixture -TestRoot $testRoot -Name 'cross-collection-collision'
    New-Skill -Central $crossFixture.Central -Name 'tdd' | Out-Null
    $crossMatt = Join-Path $testRoot 'cross-collection-collision/matt'
    New-MattFixture -Root $crossMatt -SkillPaths @('./skills/engineering/TDD') | Out-Null
    $crossStaleTarget = Join-Path $crossFixture.Central 'skills/stale-owned'
    New-Item -ItemType Directory -Force $crossStaleTarget | Out-Null
    New-DirectoryLink -Path (Join-Path $crossFixture.Shared 'stale-owned') -Target $crossStaleTarget
    Remove-Item -LiteralPath $crossStaleTarget -Recurse -Force
    Assert-Throws {
        Invoke-Reconciler -Central $crossFixture.Central -Matt $crossMatt -Shared $crossFixture.Shared
    } '*duplicate*name*tdd*' 'cross-collection basename collision fails preflight'
    Assert-True ($null -ne (Get-LinkItem (Join-Path $crossFixture.Shared 'stale-owned'))) 'cross-collection collision causes no mutation'
    Assert-Null (Get-LinkItem (Join-Path $crossFixture.Shared 'tdd')) 'cross-collection collision creates no desired link'

    foreach ($manifestCase in @('missing', 'malformed', 'wrong-name', 'not-array', 'empty-array', 'non-string')) {
        $manifestFixture = New-Fixture -TestRoot $testRoot -Name "matt-manifest-$manifestCase"
        New-Skill -Central $manifestFixture.Central -Name 'superpower-only' | Out-Null
        $manifestMatt = Join-Path $testRoot "matt-manifest-$manifestCase/matt"
        New-MattFixture -Root $manifestMatt | Out-Null
        Add-MutationSentinels -Central $manifestFixture.Central -Shared $manifestFixture.Shared
        $manifestPath = Join-Path $manifestMatt '.claude-plugin/plugin.json'
        switch ($manifestCase) {
            'missing' { Remove-Item -LiteralPath $manifestPath -Force }
            'malformed' { '{not-json' | Set-Content -NoNewline $manifestPath }
            'wrong-name' { '{"name":"wrong","skills":["./skills/engineering/matt-only"]}' | Set-Content -NoNewline $manifestPath }
            'not-array' { '{"name":"mattpocock-skills","skills":"./skills/engineering/matt-only"}' | Set-Content -NoNewline $manifestPath }
            'empty-array' { '{"name":"mattpocock-skills","skills":[]}' | Set-Content -NoNewline $manifestPath }
            'non-string' { '{"name":"mattpocock-skills","skills":[42]}' | Set-Content -NoNewline $manifestPath }
        }
        Assert-Throws {
            Invoke-Reconciler -Central $manifestFixture.Central -Matt $manifestMatt -Shared $manifestFixture.Shared
        } '*Matt*manifest*' "$manifestCase Matt manifest fails preflight"
        Assert-MutationSentinelsUntouched -Shared $manifestFixture.Shared
    }

    Write-Host "PASS: $script:AssertionCount assertions"
}
finally {
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
