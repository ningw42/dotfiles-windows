return {
  -- auto completion engine: blink.cmp
  {
    "saghen/blink.cmp",
    -- optional: provides snippets for the snippet source
    dependencies = {
      "rafamadriz/friendly-snippets",
      "echasnovski/mini.icons",
    },

    -- use a release tag to download pre-built binaries
    version = "*",
    -- AND/OR build from source, requires nightly: https://rust-lang.github.io/rustup/concepts/channels.html#working-with-nightly-rust
    -- build = "cargo build --release",
    -- If you use nix, you can build from source using latest nightly rust with:
    -- build = "nix run .#build-plugin",

    event = "InsertEnter",

    ---@module "blink.cmp"
    ---@type blink.cmp.Config
    opts = {
      -- "default" for mappings similar to built-in completion
      -- "super-tab" for mappings similar to vscode (tab to accept, arrow keys to navigate)
      -- "enter" for mappings similar to "super-tab" but with "enter" to accept
      -- See the full "keymap" documentation for information on defining your own keymap.
      keymap = {
        preset = "enter",
        ["<C-y>"] = { "select_and_accept" },
      },

      appearance = {
        -- Sets the fallback highlight groups to nvim-cmp"s highlight groups
        -- Useful for when your theme doesn"t support blink.cmp
        -- Will be removed in a future release
        use_nvim_cmp_as_default = false,
        -- Set to "mono" for "Nerd Font Mono" or "normal" for "Nerd Font"
        -- Adjusts spacing to ensure icons are aligned
        nerd_font_variant = "normal"
      },

      completion = {
        menu = {
          -- nvim-cmp style menu
          draw = {
            columns = {
              { "index" },
              { "kind_icon", "label", "label_description", gap = 1 },
              { "kind", "source_name", gap = 1 },
            },

            components = {
              -- new column type, index
              index = {
                text = function(ctx) return ctx.idx == 10 and "0" or ctx.idx >= 10 and " " or tostring(ctx.idx) end,
              },

              -- custom kind_icon with mini.icons
              kind_icon = {
                ellipsis = false,
                text = function(ctx)
                  local kind_icon, _, _ = require("mini.icons").get("lsp", ctx.kind)
                  return kind_icon .. " "
                end,
                highlight = function(ctx)
                  local _, hl, _ = require("mini.icons").get("lsp", ctx.kind)
                  return hl
                end,
              },

              -- custom kind highlight
              kind = {
                highlight = function(ctx)
                  local _, hl, _ = require("mini.icons").get("lsp", ctx.kind)
                  return hl
                end,
              },

              -- custom source_name text
              source_name = {
                width = { max = 30 },
                text = function(ctx) return "[" .. ctx.source_name .. "]" end,
                highlight = "BlinkCmpKind",
              },
            },
          },
        },
      },

      -- Default list of enabled providers defined so that you can extend it
      -- elsewhere in your config, without redefining it, due to `opts_extend`
      sources = {
        default = { "lazydev", "lsp", "path", "snippets", "buffer" },
        cmdline = {},
        providers = {
          -- enable LazyDev as a source
          lazydev = {
            name = "LazyDev",
            module = "lazydev.integrations.blink",
            -- make lazydev completions top priority (see `:h blink.cmp`)
            score_offset = 100,
          },
        },
      },
    },
    opts_extend = { "sources.default" }
  },

  -- LSP servers and clients communicate which features they support through "capabilities".
  --  By default, Neovim supports a subset of the LSP specification.
  --  With blink.cmp, Neovim has *more* capabilities which are communicated to the LSP servers.
  --  Explanation from TJ: https://youtu.be/m8C0Cq9Uv9o?t=1275
  --
  -- This can vary by config, but in general for nvim-lspconfig:
  {
    "neovim/nvim-lspconfig",
    dependencies = { "saghen/blink.cmp" },
    opts = {
      servers = {
        bashls = {},
        beancount = {},
        jsonls = {},
        docker_compose_language_service = {},
        dockerls = {},
        lua_ls = {},
        nil_ls = {},
        pyright = {},
        yamlls = {},
      },
    },
    config = function(_, opts)
      local lspconfig = require("lspconfig")
      for server, config in pairs(opts.servers) do
        -- passing config.capabilities to blink.cmp merges with the capabilities in your
        -- `opts[server].capabilities, if you"ve defined it
        config.capabilities = require("blink.cmp").get_lsp_capabilities(config.capabilities)
        lspconfig[server].setup(config)
      end
    end
  },

  -- Configures lua_ls for editing neovim configuration
  {
    "folke/lazydev.nvim",
    ft = "lua", -- only load on lua files
    opts = {
      library = {
        -- See the configuration section for more details
        -- Load luvit types when the `vim.uv` word is found
        { path = "${3rd}/luv/library", words = { "vim%.uv" } },
      },
    },
  },
}
