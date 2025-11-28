return {
  -- catppuccin
  {
    "catppuccin/nvim",
    enabled = vim.g.colorscheme == "catppuccin",
    version = false,
    lazy = false,
    priority = 1000,
    opts = {
      flavour = vim.g.colorscheme_flavor,
      integrations = {
        blink_cmp = true,
        fzf = true,
        gitsigns = true,
        noice = true,
        treesitter_context = true,
        treesitter = true,
        snacks = true,
        lsp_trouble = true,
        illuminate = {
          enabled = true,
          lsp = true,
        },
        indent_blankline = { enabled = true },
        which_key = true,
        neotree = true,
        rainbow_delimiters = true,
      },
    },
    config = function(_, opts)
      require("catppuccin").setup(opts)

      vim.o.background = vim.g.colorscheme_background
      vim.cmd.colorscheme("catppuccin")
    end,
    specs = {
      {
        "akinsho/bufferline.nvim",
        optional = true,
        opts = function(_, opts)
          opts.highlights = require("catppuccin.special.bufferline").get_theme()
        end,
      },
      {
        "nvim-lualine/lualine.nvim",
        optional = true,
        opts = {
          options = {
            theme = "catppuccin",
          },
        },
      },
    },
  },

  -- everforest
  {
    "neanias/everforest-nvim",
    enabled = vim.g.colorscheme == "everforest",
    version = false,
    lazy = false,
    priority = 1000, -- make sure to load this before all the other start plugins
    -- Optional; default configuration will be used if setup isn't called.
    config = function()
      -- we use "medium" flavor which the the default one
      vim.o.background = vim.g.colorscheme_background
      vim.cmd.colorscheme("everforest")
    end,
    specs = {
      {
        "nvim-lualine/lualine.nvim",
        optional = true,
        opts = {
          options = {
            theme = "everforest",
          },
        },
      },
    },
  },

  -- gruvbox
  {
    "ellisonleao/gruvbox.nvim",
    enabled = vim.g.colorscheme == "gruvbox",
    version = false,
    lazy = false,
    priority = 1000,
    config = function()
      -- we use "medium" flavor which the the default one
      local palette = require("gruvbox").palette
      require("gruvbox").setup({
        overrides = {
          -- NOTE: Do not reverse to fix the broken highlight in neovim 0.11 nightly
          -- Ref: https://github.com/neovim/neovim/pull/29976
          -- Ref: https://github.com/nvim-lualine/lualine.nvim/issues/1312#issuecomment-2439965065
          StatusLine = { fg = palette.dark2, bg = nil, reverse = false },
          StatusLineNC = { fg = palette.dark1, bg = nil, reverse = false },
        },
      })

      vim.o.background = vim.g.colorscheme_background
      vim.cmd.colorscheme("gruvbox")
    end,
    specs = {
      {
        "nvim-lualine/lualine.nvim",
        optional = true,
        opts = {
          options = {
            theme = "gruvbox",
          },
        },
      },
    },
  },

  -- rose-pine
  {
    "rose-pine/neovim",
    enabled = vim.g.colorscheme == "rose-pine",
    name = "rose-pine",
    config = function()
      vim.cmd("colorscheme " .. "rose-pine-" .. vim.g.colorscheme_flavor)
    end,
    specs = {
      {
        "akinsho/bufferline.nvim",
        optional = true,
        opts = function(_, opts)
          opts.highlights = require("rose-pine.plugins.bufferline")
        end,
      },
      {
        "nvim-lualine/lualine.nvim",
        optional = true,
        opts = {
          options = {
            theme = "rose-pine",
          },
        },
      },
    },
  }
}
