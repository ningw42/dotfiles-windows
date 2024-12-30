-- Bootstrap lazy.nvim
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not (vim.uv or vim.loop).fs_stat(lazypath) then
  local lazyrepo = "https://github.com/folke/lazy.nvim.git"
  local out = vim.fn.system({ "git", "clone", "--filter=blob:none", "--branch=stable", lazyrepo, lazypath })
  if vim.v.shell_error ~= 0 then
    vim.api.nvim_echo({
      { "Failed to clone lazy.nvim:\n", "ErrorMsg" },
      { out, "WarningMsg" },
      { "\nPress any key to exit..." },
    }, true, {})
    vim.fn.getchar()
    os.exit(1)
  end
end
vim.opt.rtp:prepend(lazypath)

-- Make sure to setup `mapleader` and `maplocalleader` before
-- loading lazy.nvim so that mappings are correct.
-- This is also a good place to setup other settings (vim.opt)
vim.g.mapleader = " "
vim.g.maplocalleader = "\\"

-- Setup lazy.nvim
require("lazy").setup({
  spec = {
    -- import your plugins
    { import = "plugins" },
  },
  -- Configure any other settings here. See the documentation for more details.
  -- colorscheme that will be used when installing plugins.
  install = { colorscheme = { "gruvbox" } },
  -- automatically check for plugin updates
  checker = { enabled = true },
})

-- general neovim/vim configurations
local opt = vim.opt
opt.number = true -- line number
opt.relativenumber = true -- relative line number
opt.tabstop = 2 -- the width of a TAB is set to 2. still it is a \t. It is just that Vim will interpret it to be having a width of 2.
opt.shiftwidth = 2 -- indents will have a width of 2
opt.softtabstop = 2 -- sets the number of columns for a TAB
opt.shiftround = true -- round indent to multiple of 'shiftwidth'
opt.expandtab = true -- expand TABs to spaces
opt.smartcase = true -- don't ignore case with capitals
opt.ignorecase = true -- ignore case in search patterns
opt.smartindent = true -- better indent
opt.cursorline = true -- highlight cursor line
opt.termguicolors = true -- enable termguicolors
opt.clipboard = "unnamedplus" -- sync with system clipboard
opt.showmode = false -- disable showmode
opt.splitbelow = true -- new windows below current
opt.splitright = true -- new windows to the right of current
opt.list = true -- show invisible characters
opt.laststatus = 3 -- global status line
opt.listchars = { -- define how invisible characters are shown
  tab = "» ",
  extends = "›",
  trail = "·",
  precedes = "‹",
  nbsp = "␣",
}
