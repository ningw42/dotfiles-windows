# scoop
Write-Progress -Activity "Installing dependencies" -Status "Installing scoop" -PercentComplete 5
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
Invoke-RestMethod -Uri https://get.scoop.sh | Invoke-Expression

# neovim
Write-Progress -Activity "Installing dependencies" -Status "Installing neovim" -PercentComplete 10
scoop install neovim
Write-Progress -Activity "Installing dependencies" -Status "Installing neovim dependencies" -PercentComplete 15
scoop install llvm fzf ripgrep nodejs

# yazi
Write-Progress -Activity "Installing dependencies" -Status "Installing yazi" -PercentComplete 20
scoop install yazi # yazi
Write-Progress -Activity "Installing dependencies" -Status "Installing yazi dependencies" -PercentComplete 25
scoop install ffmpeg 7zip jq poppler fd ripgrep fzf zoxide imagemagick # yazi's direct dependencies
Write-Progress -Activity "Installing dependencies" -Status "Installing yazi plugin dependencies" -PercentComplete 30
scoop install exiftool eza glow hexyl mediainfo # yazi's plugin dependencies

# fastfetch
Write-Progress -Activity "Installing dependencies" -Status "Installing fastfetch" -PercentComplete 35
scoop install fastfetch

# starship
Write-Progress -Activity "Installing dependencies" -Status "Installing starship" -PercentComplete 40
scoop install starship

# gitui
Write-Progress -Activity "Installing dependencies" -Status "Installing gitui" -PercentComplete 40
scoop install gitui
