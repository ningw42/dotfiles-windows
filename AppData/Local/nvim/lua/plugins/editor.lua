return {
  -- auto pairs: mini.pairs
  {
    "echasnovski/mini.pairs",
    version = "*",
    event = "VeryLazy",
    opts = {},
  },

  -- comments: mini.comment
  {
    "echasnovski/mini.comment",
    version = "*",
    event = "VeryLazy",
    dependencies = {
      {
        "JoosepAlviste/nvim-ts-context-commentstring",
        lazy = true,
        opts = {
          enable_autocmd = false,
        },
      },
    },
    opts = {
      options = {
        custom_commentstring = function()
          return require("ts_context_commentstring.internal").calculate_commentstring() or vim.bo.commentstring
        end,
      },
    },
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
}
