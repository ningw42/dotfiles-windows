return {
  -- auto pairs: mini.pairs
  {
    "echasnovski/mini.pairs",
    version = "*",
    event = "VeryLazy",
    opts = {},
  },

  -- comments: ts-comments
  {
    "folke/ts-comments.nvim",
    opts = {
      lang = {
        ron = "// %s", -- Rusty Object Notation
      },
    },
    event = "VeryLazy",
  },

  -- selection highlight: vim-illuminate
  {
    "RRethy/vim-illuminate",
    version = false,
    opts = {
      filetypes_denylist = {
        -- default filetype denylist
        "dirbuf",
        "dirvish",
        "fugitive",

        -- customized filetype denylist
        "help",
        "dashboard",
        "neo-tree",
        "Trouble",
        "lazy",
        "notify",
      },
    },
    config = function(_, opts)
      require("illuminate").configure(opts)
    end,
  },

  -- markdown preview: markview
  {
    "OXY2DEV/markview.nvim",
    lazy = false,
    opts = {
      preview = {
        icon_provider = "mini",
      },
    },
  },

  -- better help view: helpview
  {
    "OXY2DEV/helpview.nvim",
    lazy = false,
  },

  -- rainbow parentheses: rainbow-delimiters
  {
    "HiPhish/rainbow-delimiters.nvim",
  },
}
