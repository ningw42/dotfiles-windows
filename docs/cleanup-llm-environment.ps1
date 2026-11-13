# Human-only migration. This file is repo-only and is never invoked by chezmoi.
# Preview: pwsh -NoProfile -File ./docs/cleanup-llm-environment.ps1
# Remove:  pwsh -NoProfile -File ./docs/cleanup-llm-environment.ps1 -Apply
# Optional tools: add -IncludeMcp after arranging external MCP credentials.
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [switch]$Apply,
    [switch]$IncludeMcp
)

$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'This migration only supports Windows.' }

$names = @(
    'COPILOTD_API_KEY', 'MAGPIE_API_KEY', 'DEEPSEEK_API_KEY',
    'CODEX_API_KEY', 'PI_API_KEY', 'OPENCODE_API_KEY',
    'ROUTER_MAESTRO_API_KEY', 'COPILOT_PROXY_API_KEY', 'LITELLM_API_KEY',
    'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'YYLX_API_KEY',
    'ANTHROPIC_BASE_URL', 'ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
    'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
    'ANTHROPIC_DEFAULT_FABLE_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL',
    'CLAUDE_CODE_EFFORT_LEVEL', 'CLAUDE_CODE_AUTO_COMPACT_WINDOW'
)
if ($IncludeMcp) { $names += @('CONTEXT7_API_KEY', 'GITHUB_PERSONAL_ACCESS_TOKEN') }

Write-Warning 'Removing MAGPIE_API_KEY disables environment-based OpenCode authentication until supplied separately.'
Write-Warning 'This does not revoke keys, change native login stores, or erase values already inherited by other processes.'
foreach ($name in $names) {
    foreach ($scope in @('User', 'Process')) {
        $present = $null -ne [Environment]::GetEnvironmentVariable($name, $scope)
        if (-not $present) { continue }
        if (-not $Apply) {
            Write-Output "Would remove $scope environment entry: $name"
        } elseif ($PSCmdlet.ShouldProcess("$scope environment entry $name", 'Remove')) {
            [Environment]::SetEnvironmentVariable($name, $null, $scope)
            Write-Output "Removed $scope environment entry: $name"
        }
    }
}
if (-not $Apply) { Write-Output 'Preview only. Supply -Apply to remove the listed entries (confirmation required).' }
Write-Output 'Restart terminals, launchers, and affected clients after cleanup. A child PowerShell cannot modify its parent environment.'
