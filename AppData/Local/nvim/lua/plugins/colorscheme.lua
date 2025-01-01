return {
  -- gruvbox dark
  {
    "ellisonleao/gruvbox.nvim",
    priority = 1000, -- always load colorscheme first, default value of priority is 50
    config = function()
      vim.o.background = "dark"
      vim.cmd([[colorscheme gruvbox]])
    end,
  },
}

