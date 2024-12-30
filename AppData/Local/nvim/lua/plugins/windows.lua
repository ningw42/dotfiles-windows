return {
  -- Windows specific: use mason to manage LSP installs
  {
    "williamboman/mason.nvim",
    opts = {
      PATH = "prepend",
    },
    config = function(_, opts)
      require("mason").setup(opts)
    end,
  },
  {
    "williamboman/mason-lspconfig.nvim",
    dependencies = {
        "neovim/nvim-lspconfig",
        "williamboman/mason.nvim",
    },
    opts = {
      ensure_installed = {
        "jsonls",
        "lua_ls",
        "pyright",
        "yamlls"
      },
    },
  },
}
