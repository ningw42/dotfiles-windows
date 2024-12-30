#region Environment Variables

# yazi's file executable.
# see https://yazi-rs.github.io/docs/installation#windows
$Env:YAZI_FILE_ONE = "C:\Users\ningw\scoop\apps\git\current\usr\bin\file.exe"

# exa/eza, the number of spaces to print between icon and filename.
# TODO: when eza change this to the proper name, replace it.
$Env:EXA_ICON_SPACING = 2

#endregion Environment Variables


#region Aliases

Set-Alias -Name y -Value Invoke-Yazi
Set-Alias -Name cdcz -Value Enter-ChezmoiRepository
Set-Alias -Name l -Value Get-ChildItemEza
Set-Alias -Name ll -Value Get-ChildItemEzaLong
Set-Alias -Name lt -Value Get-ChildItemEzaTree
Set-Alias -Name llt -Value Get-ChildItemEzaTreeLong

#endregion Aliases


#region Functions

function Enter-ChezmoiRepository
{
  cd $(chezmoi source-path)
}

function Invoke-Yazi
{
    $tmp = [System.IO.Path]::GetTempFileName()
    yazi $args --cwd-file="$tmp"
    $cwd = Get-Content -Path $tmp
    if (-not [String]::IsNullOrEmpty($cwd) -and $cwd -ne $PWD.Path) {
        Set-Location -LiteralPath $cwd
    }
    Remove-Item -Path $tmp
}

Function Get-ChildItemEza
{
  eza --group-directories-first --icons --long --group --header --time-style=iso --binary --all
}

Function Get-ChildItemEzaLong
{
  eza --group-directories-first --icons --long --group --header --accessed --modified --created --time-style=iso --binary --all
}

Function Get-ChildItemEzaTree
{
  eza --group-directories-first --icons --long --group --header --time-style=iso --binary --tree
}

Function Get-ChildItemEzaTreeLong
{
  eza --group-directories-first --icons --long --group --header --accessed --modified --created --time-style=iso --binary --tree
}

#endregion Functions


# This has to be the last expression in this file
Invoke-Expression (&starship init powershell)

