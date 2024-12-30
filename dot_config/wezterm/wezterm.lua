-- Pull in the wezterm API
local wezterm = require 'wezterm'

-- This will hold the configuration.
local config = wezterm.config_builder()

-- Global Constants
local font_fallback_list = wezterm.font_with_fallback {
	-- 'Iosevkata Nerd Font',
	'PragmataPro',
	'Sarasa Fixed SC',
}

-- This is where you actually apply your config choices

-- Launching Programs
config.default_prog = { 'powershell.exe' }

-- Color Scheme
config.color_scheme = 'GruvboxDark'

-- Tab Bar
config.window_decorations = 'RESIZE'
config.window_frame = {
	font = font_fallback_list,
	font_size = 10.0,
}

-- Fonts
config.font = font_fallback_list
config.font_size = 10.0
config.line_height = 1.0

config.default_ssh_auth_sock = '\\\\.\\pipe\\openssh-ssh-agent'
-- config.ssh_backend = 'Ssh2'

-- and finally, return the configuration to wezterm
return config
