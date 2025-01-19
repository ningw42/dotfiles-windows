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

config.initial_cols = 160
config.initial_rows = 40

-- Launching Programs
config.default_prog = { 'pwsh.exe' }

-- Color Scheme
config.color_scheme = 'GruvboxDark'

-- Tab Bar
config.tab_bar_at_bottom = true

-- Window
config.window_decorations = 'RESIZE'
config.window_frame = {
	font = font_fallback_list,
	font_size = 10.0,
}
config.window_padding = {
  left = '0.5cell',
  right = '0.5cell',
  top = '0.5cell',
  bottom = 0,
}

-- Fonts
config.font = font_fallback_list
config.font_size = 10.0
config.line_height = 1.0

-- WezTerm reads ssh configuration
config.ssh_backend = 'Ssh2'

-- to match main monitor's refresh rate
config.max_fps = 240

-- and finally, return the configuration to wezterm
return config
