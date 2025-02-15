#region Environment Variables

# yazi: file(1) executable
# see https://yazi-rs.github.io/docs/installation#windows
$Env:YAZI_FILE_ONE = "C:\Users\ningw\scoop\apps\git\current\usr\bin\file.exe"

# eza: the number of spaces to print between icon and filename
$Env:EZA_ICON_SPACING = 2

# bat config directory
$Env:BAT_CONFIG_DIR = "C:\Users\ningw\.config\bat"

#endregion Environment Variables


#region Functions

# alias for chezmoi
function cz
{
  chezmoi $args
}

# alias for entering local chezmoi repository
function czcd
{
  Set-Location $(chezmoi source-path)
}

# alias for launching yazi
function y
{
    $tmp = [System.IO.Path]::GetTempFileName()
    yazi $args --cwd-file="$tmp"
    $cwd = Get-Content -Path $tmp
    if (-not [String]::IsNullOrEmpty($cwd) -and $cwd -ne $PWD.Path) {
        Set-Location -LiteralPath $cwd
    }
    Remove-Item -Path $tmp
}

Function l
{
  eza --icons --no-quotes --group-directories-first --no-symlinks $args
}

Function ll
{
  eza --header --icons --long --octal-permissions --binary --group --time-style='+%F %T' --color-scale=age --no-quotes --group-directories-first --all $args
}

Function lt
{
  eza --header --icons --long --octal-permissions --binary --group --time-style='+%F %T' --color-scale=age --no-quotes --group-directories-first --all --tree $args
}

#endregion Functions


# This is recommended to be the last expression in $PROFILE
Invoke-Expression (&starship init powershell)

# But zoxide doesn't work if it is before starship, see https://github.com/ajeetdsouza/zoxide/issues/74
Invoke-Expression (& { (zoxide init powershell | Out-String) })
