#region Environment Variables

# yazi's file executable.
# see https://yazi-rs.github.io/docs/installation#windows
$Env:YAZI_FILE_ONE = "C:\Users\ningw\scoop\apps\git\current\usr\bin\file.exe"

# exa/eza, the number of spaces to print between icon and filename.
# TODO: when eza change this to the proper name, replace it.
$Env:EXA_ICON_SPACING = 2

#endregion Environment Variables


#region Functions

# entering the local chezmoi repository
function cdcz
{
  cd $(chezmoi source-path)
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
  eza --group-directories-first --icons --long --group --header --time-style=iso --binary --all $args
}

Function ll
{
  eza --group-directories-first --icons --long --group --header --accessed --modified --created --time-style=iso --binary --all $args
}

Function lt
{
  eza --group-directories-first --icons --long --group --header --time-style=iso --binary --tree $args
}

Function llt
{
  eza --group-directories-first --icons --long --group --header --accessed --modified --created --time-style=iso --binary --tree $args
}

#endregion Functions


# This has to be the last expression in this file
Invoke-Expression (&starship init powershell)

