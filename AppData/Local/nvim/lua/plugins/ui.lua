local indent_hint_char = "▏"
-- local indent_hint_char = "│"

return {
  -- snacks.nvim
  -- currently used as a dashboard
  {
    "folke/snacks.nvim",
    priority = 1000,
    lazy = false,
    ---@type snacks.Config
    opts = {
      -- unlike other plugins, components are enabled iff they are configured explicitly, or enabled is set to true for default settings.
      dashboard = {
        sections = {
          { pane = 1, section = "header", },
          { pane = 1, section = "keys", gap = 1, padding = 1 },
          { pane = 1, section = "startup" },
          {
            pane = 2,
            section = "terminal",
            cmd = "colorscript -e square",
            height = 5,
            padding = 1,
          },
          { pane = 2, icon = " ", title = "Recent Files", section = "recent_files", indent = 2, padding = 1 },
          { pane = 2, icon = " ", title = "Projects", section = "projects", indent = 2, padding = 1 },
          {
            pane = 2,
            icon = " ",
            title = "Git Status",
            section = "terminal",
            enabled = function()
              return Snacks.git.get_root() ~= nil
            end,
            cmd = "git status --short --branch --renames",
            height = 5,
            padding = 1,
            ttl = 5 * 60,
            indent = 3,
          },
        },
      },
    },
  },

  -- tree-like file explorer: neo-tree.nvim
  {
    "nvim-neo-tree/neo-tree.nvim",
    version = "3.*",
    dependencies = {
      "nvim-lua/plenary.nvim",
      "echasnovski/mini.icons",
      "MunifTanjim/nui.nvim",
    },
    cmd = "Neotree",
    keys = {
      {
        "<leader>te", -- te, toggle explorer
        function()
          require("neo-tree.command").execute({ toggle = true })
        end,
        desc = "Toggle NeoTree",
      },
    },
    init = function()
      vim.g.neo_tree_remove_legacy_commands = 1
    end,
    config = function()
      local highlights = require("neo-tree.ui.highlights")
      local miniicons = require("mini.icons")

      -- configs
      require("neo-tree").setup({
        close_if_last_window = true,
        default_component_configs = {
          indent = {
            indent_size = 1, -- smaller indent size, default is 2
          },
          icon = {
            folder_closed = "󰉋",
            folder_open = "󰝰",
            folder_empty = "󰷏",
            padding = "  ", -- with the customized `filesystem.components.icon` below, we can use `padding` here to add an extra space after icon.
          },
        },
        filesystem = {
          -- show dotfiles but not .git directory
          filtered_items = {
            hide_dotfiles = false,
            never_show = { ".git" },
          },
          components = {
            -- this is basically a copy of M.icon in https://github.com/nvim-neo-tree/neo-tree.nvim/blob/main/lua/neo-tree/sources/common/components.lua,
            -- to add configurable padding support. see also https://github.com/nvim-neo-tree/neo-tree.nvim/wiki/Recipes#custom-icons.
            icon = function(config, node, state)
              local icon = config.default or " "
              local padding = config.padding or " "
              local highlight = config.highlight or highlights.FILE_ICON
              if node.type == "directory" then
                highlight = highlights.DIRECTORY_ICON
                if node.loaded and not node:has_children() then
                  icon = not node.empty_expanded and config.folder_empty or config.folder_empty_open
                elseif node:is_expanded() then
                  icon = config.folder_open or "-"
                else
                  local miniicon _, _ = miniicons.get("directory", node.name)
                  icon = miniicon or config.folder_closed or "+"
                end
              elseif node.type == "file" or node.type == "terminal" then
                local miniicon, hl, _ = miniicons.get("file", node.name)
                icon = miniicon or icon
                highlight = hl or highlight
              end

              return {
                text = icon .. padding,
                highlight = highlight,
              }
            end
          },
        },
      })
    end,
  },

  -- tabbar: bufferline.nvim
  {
    "akinsho/bufferline.nvim",
    version = "*",
    event = "VimEnter",
    dependencies = { "echasnovski/mini.icons" },
    keys = {
      { "<leader>bp", "<cmd>BufferLinePick<cr>", desc = "Buffer Picker" },
      { "<leader>b[", "<cmd>BufferLineCyclePrev<cr>", desc = "Cycle Prev Buffer" },
      { "<leader>b]", "<cmd>BufferLineCycleNext<cr>", desc = "Cycle Next Buffer" },
    },
    opts = {
      options = {
        -- bufferline offset for neo-tree
        offsets = {
          {
            filetype = "neo-tree",
            text = "NeoTree",
            highlight = "Directory",
            text_align = "center",
            separator = true,
          },
        },
      },
    },
  },

  -- statusline: lualine.nvim
  {
    "nvim-lualine/lualine.nvim",
    event = "VimEnter",
    opts = {
      options = {
        icons_enabled = true,
        theme = "gruvbox_dark",
        globalstatus = true,
        -- disable lualine for dashboard.nvim and neo-tree
        disabled_filetypes = { statusline = { "dashboard", "neo-tree" } },
        component_separators = { left = "", right = "" },
        section_separators = { left = "", right = "" },
      },
      sections = {
        lualine_a = { "mode" },
        lualine_b = {
          {
            "branch",
            icon = " ",
          },
          "diff",
          {
            "filename",
            symbols = {
              modified = "●",
              readonly = "",
              unnamed = "[New]",
              newfile = "",
            },
          },
        },
        lualine_c = {},
        lualine_x = { "diagnostics" },
        lualine_y = {
          "encoding",
          {
            "filetype",
            colored = false,
            icon_only = true,
            padding = { left = 1, right = 2 }, -- extra padding to the right
          },
          {
            "fileformat",
            padding = { left = 1, right = 2 }, -- extra padding to the right
          },
        },
        lualine_z = {
          "progress",
          {
            "location",
            fmt = function()
              local line = vim.fn.line(".")
              local col = vim.fn.virtcol(".")
              local total_line = vim.fn.line("$")
              return string.format(":%d/%d :%d", line, total_line, col)
            end,
          },
        },
      },
      extensions = { "neo-tree" },
    },
  },

  -- indent guides: indent-blankline
  {
    "lukas-reineke/indent-blankline.nvim",
    main = "ibl",
    event = { "BufReadPost", "BufNewFile" },
    opts = {
      indent = {
        char = indent_hint_char,
        tab_char = indent_hint_char,
      },
      scope = { enabled = false },
      exclude = {
        filetypes = {
          "help",
          "dashboard",
          "neo-tree",
          "Trouble",
          "lazy",
          "notify",
        },
      },
    },
  },

  -- active indent guide and indent text objects: mini.indentscope
  {
    "echasnovski/mini.indentscope",
    version = false, -- wait till new 0.7.0 release to put it back on semver
    event = { "BufReadPre", "BufNewFile" },
    opts = {
      symbol = indent_hint_char,
      options = { try_as_border = true },
    },
    init = function()
      vim.api.nvim_create_autocmd("FileType", {
        pattern = { "help", "dashboard", "neo-tree", "Trouble", "lazy", "notify" },
        callback = function()
          vim.b.miniindentscope_disable = true
        end,
      })
    end,
    config = function(_, opts)
      require("mini.indentscope").setup(opts)
    end,
  },

  -- git decorations for buffer: gitsigns.nvim
  {
    "lewis6991/gitsigns.nvim",
    event = { "BufReadPre", "BufNewFile" },
    opts = {
      signs = {
        add = { text = "▎" },
        change = { text = "▎" },
        delete = { text = "" },
        topdelete = { text = "" },
        changedelete = { text = "▎" },
        untracked = { text = "▎" },
      },
    },
  },

  -- fzf-lua
  {
    "ibhagwan/fzf-lua",
    dependencies = { "echasnovski/mini.icons" },
    cmd = "FzfLua",
    opts = {
      file_icon_padding = " ",
    },
    keys = {
      -- Find
      {
        "<leader>fb",
        function()
          return require("fzf-lua").buffers()
        end,
        desc = "Find Buffers",
      },
      {
        "<leader>ff",
        function()
          return require("fzf-lua").files()
        end,
        desc = "Find Files",
      },
      {
        "<leader>fF",
        function()
          return require("fzf-lua").lgrep_curbuf()
        end,
        desc = "Fuzzy Find",
      },
      {
        "<leader>fg",
        function()
          return require("fzf-lua").live_grep_native()
        end,
        desc = "Global Find",
      },

      -- Git
      {
        "<leader>Gs",
        function()
          return require("fzf-lua").git_status()
        end,
        desc = "Git Status",
      },
      {
        "<leader>Gc",
        function()
          return require("fzf-lua").git_commits()
        end,
        desc = "Git Commits",
      },

      -- Goto
      {
        "<leader>gd",
        function()
          return require("fzf-lua").lsp_definitions()
        end,
        desc = "Goto Definition",
      },
      {
        "<leader>gr",
        function()
          return require("fzf-lua").lsp_references()
        end,
        desc = "Goto References",
      },
    },
  },

  -- shortcut hints: which-key
  {
    "folke/which-key.nvim",
    event = "VeryLazy",
    opts_extend = { "spec" },
    opts = {
      defaults = {},
      spec = {
        {
          mode = { "n", "v" },
          { "<leader><tab>", group = "tabs" },
          { "<leader>c", group = "code" },
          { "<leader>f", group = "file/find" },
          { "<leader>g", group = "git" },
          { "<leader>gh", group = "hunks" },
          { "<leader>q", group = "quit/session" },
          { "<leader>s", group = "search" },
          { "<leader>u", group = "ui", icon = { icon = "󰙵 ", color = "cyan" } },
          { "<leader>x", group = "diagnostics/quickfix", icon = { icon = "󱖫 ", color = "green" } },
          { "[", group = "prev" },
          { "]", group = "next" },
          { "g", group = "goto" },
          { "gs", group = "surround" },
          { "z", group = "fold" },
          {
            "<leader>b",
            group = "buffer",
            expand = function()
              return require("which-key.extras").expand.buf()
            end,
          },
          {
            "<leader>w",
            group = "windows",
            proxy = "<c-w>",
            expand = function()
              return require("which-key.extras").expand.win()
            end,
          },
          -- better descriptions
          { "gx", desc = "Open with system app" },
        },
      },
    },
    keys = {
      {
        "<leader>?",
        function()
          require("which-key").show({ global = false })
        end,
        desc = "Buffer Keymaps (which-key)",
      },
      {
        "<c-w><space>",
        function()
          require("which-key").show({ keys = "<c-w>", loop = true })
        end,
        desc = "Window Hydra Mode (which-key)",
      },
    },
    config = function(_, opts)
      local wk = require("which-key")
      wk.setup(opts)
      if not vim.tbl_isempty(opts.defaults) then
        LazyVim.warn("which-key: opts.defaults is deprecated. Please use opts.spec instead.")
        wk.register(opts.defaults)
      end
    end,
  },

  -- diagnostics viewer: trouble
  {
    "folke/trouble.nvim",
    dependencies = { "echasnovski/mini.icons" },
    keys = {
      {
        "<leader>td", -- td, toggle diagnostics
        function()
          require("trouble").toggle()
        end,
        desc = "Toggle Trouble",
      },
    },
  },

  -- icons
  {
    "echasnovski/mini.icons",
    lazy = true,
    opts = {
      file = {
        [".keep"] = { glyph = "󰊢", hl = "MiniIconsGrey" },
        ["devcontainer.json"] = { glyph = "", hl = "MiniIconsAzure" },
      },
      filetype = {
        dotenv = { glyph = "", hl = "MiniIconsYellow" },
      },
    },
    init = function()
      package.preload["nvim-web-devicons"] = function()
        require("mini.icons").mock_nvim_web_devicons()
        return package.loaded["nvim-web-devicons"]
      end
    end,
  },

  -- better vim.ui
  {
    "stevearc/dressing.nvim",
  },

  -- notification manager: nvim-notify
  {
    "rcarriga/nvim-notify",
  },

  -- noice.nvim
  -- Highly experimental plugin that completely replaces the UI for messages, cmdline and the popupmenu.
  {
    "folke/noice.nvim",
    event = "VeryLazy",
    opts = {
      cmdline = {
        format = {
          cmdline = { icon = "❯" }, -- a custom icon to match shell
        },
      },
      lsp = {
        -- override markdown rendering so that **cmp** and other plugins use **Treesitter**
        override = {
          ["vim.lsp.util.convert_input_to_markdown_lines"] = true,
          ["vim.lsp.util.stylize_markdown"] = true,
          ["cmp.entry.get_documentation"] = true, -- requires hrsh7th/nvim-cmp
        },
      },
      -- you can enable a preset for easier configuration
      presets = {
        bottom_search = true, -- use a classic bottom cmdline for search
        command_palette = true, -- position the cmdline and popupmenu together
        long_message_to_split = true, -- long messages will be sent to a split
        inc_rename = false, -- enables an input dialog for inc-rename.nvim
        lsp_doc_border = false, -- add a border to hover docs and signature help
      },
    },
    dependencies = {
      -- if you lazy-load any plugin below, make sure to add proper `module="..."` entries
      "MunifTanjim/nui.nvim",
      -- OPTIONAL:
      --   `nvim-notify` is only needed, if you want to use the notification view.
      --   If not available, we use `mini` as the fallback
      "rcarriga/nvim-notify",
    }
  }
}
