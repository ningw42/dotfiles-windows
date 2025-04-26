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
        formats = {
          -- custom item formatter to support icon specific highlight
          icon = function(item)
            if item.file and item.icon == "file" or item.icon == "directory" then
              local icon_provider = require("mini.icons")
              local icon, hl, _ = icon_provider.get(item.icon, item.file)
              return { icon, width = 2, hl = hl or "icon" }
            end
            return { item.icon, width = 2, hl = item.icon.hl or "Constant" }
          end,
        },
        sections = {
          { pane = 1, section = "header", padding = 1 },
          -- customized builtin 'startup' to add neovim version information
          function()
            local version_info = vim.version()
            local version = version_info.major .. "." .. version_info.minor .. "." .. version_info.patch
            local lazy_stats = require("lazy.stats").stats()
            local ms = (math.floor(lazy_stats.startuptime * 100 + 0.5) / 100)
            local icon = "  "
            return {
              pane = 1,
              align = "center",
              padding = 1,
              text = {
                { icon .. "Neovim(" .. version .. ") loaded ", hl = "footer" },
                { lazy_stats.loaded .. "/" .. lazy_stats.count, hl = "special" },
                { " plugins in ", hl = "footer" },
                { ms .. "ms", hl = "special" },
              },
            }
          end,
          { pane = 1, section = "keys", gap = 1, padding = 1 },
          -- weekday ascii art
          function()
            local weekday_ascii_arts = {
              ["Monday"] = [[
███╗   ███╗ ██████╗ ███╗   ██╗
████╗ ████║██╔═══██╗████╗  ██║
██╔████╔██║██║   ██║██╔██╗ ██║
██║╚██╔╝██║██║   ██║██║╚██╗██║
██║ ╚═╝ ██║╚██████╔╝██║ ╚████║
╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝]],
              ["Tuesday"] = [[
████████╗██╗   ██╗███████╗
╚══██╔══╝██║   ██║██╔════╝
   ██║   ██║   ██║█████╗  
   ██║   ██║   ██║██╔══╝  
   ██║   ╚██████╔╝███████╗
   ╚═╝    ╚═════╝ ╚══════╝]],
              ["Wednesday"] = [[
██╗    ██╗███████╗██████╗ 
██║    ██║██╔════╝██╔══██╗
██║ █╗ ██║█████╗  ██║  ██║
██║███╗██║██╔══╝  ██║  ██║
╚███╔███╔╝███████╗██████╔╝
 ╚══╝╚══╝ ╚══════╝╚═════╝ ]],
              ["Thursday"] = [[
████████╗██╗  ██╗██╗   ██╗
╚══██╔══╝██║  ██║██║   ██║
   ██║   ███████║██║   ██║
   ██║   ██╔══██║██║   ██║
   ██║   ██║  ██║╚██████╔╝
   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ]],
              ["Friday"] = [[
███████╗██████╗ ██╗
██╔════╝██╔══██╗██║
█████╗  ██████╔╝██║
██╔══╝  ██╔══██╗██║
██║     ██║  ██║██║
╚═╝     ╚═╝  ╚═╝╚═╝]],
              ["Saturday"] = [[
███████╗ █████╗ ████████╗
██╔════╝██╔══██╗╚══██╔══╝
███████╗███████║   ██║   
╚════██║██╔══██║   ██║   
███████║██║  ██║   ██║   
╚══════╝╚═╝  ╚═╝   ╚═╝   ]],
              ["Sunday"] = [[
███████╗██╗   ██╗███╗   ██╗
██╔════╝██║   ██║████╗  ██║
███████╗██║   ██║██╔██╗ ██║
╚════██║██║   ██║██║╚██╗██║
███████║╚██████╔╝██║ ╚████║
╚══════╝ ╚═════╝ ╚═╝  ╚═══╝]],
            }
            local weekdays = { "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday" }
            local weekday = weekdays[os.date("*t").wday]
            local weekday_ascii_art = weekday_ascii_arts[weekday]
            return {
              pane = 2,
              enabled = function()
                return vim.o.columns > 80
              end, -- only enabled if the number of columns is greater than 80
              text = { weekday_ascii_art, hl = "MiniIconsCyan" },
              align = "center",
              padding = 1,
            }
          end,
          -- timestamp
          function()
            local timestamp = os.date("%Y-%m-%d %H:%M:%S")
            return {
              pane = 2,
              enabled = function()
                return vim.o.columns > 80
              end, -- only enabled if the number of columns is greater than 80
              text = { "  " .. timestamp, hl = "MiniIconsCyan" },
              align = "center",
              padding = 1,
            }
          end,
          {
            pane = 2,
            icon = { " ", hl = "MiniIconsAzure" },
            title = "Recent Files",
            section = "recent_files",
            indent = 2,
            padding = 1,
            enabled = function()
              return vim.o.columns > 80
            end,
          }, -- only enabled if the number of columns is greater than 80
          {
            pane = 2,
            icon = { " ", hl = "MiniIconsAzure" },
            title = "Projects",
            section = "projects",
            indent = 2,
            padding = 1,
            enabled = function()
              return vim.o.columns > 80
            end,
          }, -- only enabled if the number of columns is greater than 80
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
      local icon_provider = require("mini.icons")

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
                  local icon_override
                  _, _ = icon_provider.get("directory", node.name)
                  icon = icon_override or config.folder_closed or "+"
                end
              elseif node.type == "file" or node.type == "terminal" then
                local icon_override, highlight_override, _ = icon_provider.get("file", node.name)
                icon = icon_override or icon
                highlight = highlight_override or highlight
              end

              return {
                text = icon .. padding,
                highlight = highlight,
              }
            end,
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
        buffer_close_icon = "󰅖 ",
        modified_icon = "● ",
        close_icon = " ",
        left_trunc_marker = " ",
        right_trunc_marker = " ",
        color_icons = true,

        -- use mini.icons as provider
        get_element_icon = function(element)
          local icon_provider = require("mini.icons")
          local icon, hl, _ = icon_provider.get("extension", element.extension)
          return icon, hl
        end,

        -- bufferline offset for neo-tree
        offsets = {
          {
            filetype = "neo-tree",
            text = "Explorer",
            highlight = "Directory",
            text_align = "center",
            separator = true,
          },
        },
      },
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
        add = { text = "▐" },
        change = { text = "▐" },
        delete = { text = "" },
        topdelete = { text = "" },
        changedelete = { text = "▐" },
        untracked = { text = "▐" },
      },
      signs_staged = {
        add = { text = "▐" },
        change = { text = "▐" },
        delete = { text = "" },
        topdelete = { text = "" },
        changedelete = { text = "▐" },
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
    cmd = "Trouble",
    opts = {},
    keys = {
      {
        "<leader>td", -- td, toggle diagnostics for current buffer
        "<cmd>Trouble diagnostics toggle filter.buf=0<cr>",
        desc = "Toggle Diagnostics (Current Buffer)",
      },
      {
        "<leader>tD", -- td, toggle diagnostics
        "<cmd>Trouble diagnostics toggle<cr>",
        desc = "Toggle Diagnostics",
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
    },
  },

  -- color highlighter: nvim-highlight-colors
  {
    "brenoprata10/nvim-highlight-colors",
    event = "BufReadPost",
    opts = {
      render = "virtual",
      virtual_symbol = "",
      virtual_symbol_prefix = "",
      virtual_symbol_suffix = "",
      virtual_symbol_position = "eol",
      exclude_filetypes = { "lazy" },

      ---Highlight short hex colors e.g. '#fff'
      enable_short_hex = false,
      ---Highlight named colors, e.g. 'green'
      enable_named_colors = false,
    },
    config = function(_, opts)
      require("nvim-highlight-colors").setup(opts)
    end,
  },

  -- breadcrumbs: nvim-navic
  {
    "SmiteshP/nvim-navic",
    event = "LspAttach",
    dependencies = {
      "neovim/nvim-lspconfig",
    },
    opts = {
      icons = {
        File = " ",
        Module = " ",
        Namespace = " ",
        Package = " ",
        Class = " ",
        Method = " ",
        Property = " ",
        Field = " ",
        Constructor = " ",
        Enum = " ",
        Interface = " ",
        Function = " ",
        Variable = " ",
        Constant = " ",
        String = " ",
        Number = " ",
        Boolean = " ",
        Array = " ",
        Object = " ",
        Key = " ",
        Null = " ",
        EnumMember = " ",
        Struct = " ",
        Event = " ",
        Operator = " ",
        TypeParameter = " ",
      },
      lsp = {
        auto_attach = true,
        preference = nil,
      },
      highlight = true,
      separator = " > ",
      depth_limit = 0,
      depth_limit_indicator = "..",
      safe_output = true,
      lazy_update_context = false,
      click = false,
      format_text = function(text)
        return text
      end,
    },
    config = function(_, opts)
      -- always show winbar
      vim.opt.winbar = " "
      require("nvim-navic").setup(opts)
    end,
  },

  -- toggleterm, A neovim lua plugin to help easily manage multiple terminal windows.
  {
    "akinsho/toggleterm.nvim",
    version = "*",
    keys = {
      {
        "<leader>tt", -- tt, toggle terminal
        "<cmd>lua Toggleterm_term()<CR>",
        desc = "Toggle terminal",
      },
      {
        "<leader>tg", -- tg, toggle terminal launching lazygit
        "<cmd>lua Toggleterm_lazygit()<CR>",
        desc = "Toggle git",
      },
    },
    opts = {
      shade_terminals = false,
      start_in_insert = true,
      float_opts = {
        border = "curved",
        title_pos = "center",
      },
    },
    config = function(_, opts)
      require("toggleterm").setup(opts)
      local Terminal = require("toggleterm.terminal").Terminal

      local lazygit = Terminal:new({
        cmd = "lazygit",
        dir = "git_dir",
        hidden = true,
        direction = "float",
      })
      function Toggleterm_lazygit()
        lazygit:toggle()
      end

      local term = Terminal:new({
        dir = "git_dir",
        hidden = true,
        direction = "float",
      })
      function Toggleterm_term()
        term:toggle()
      end
    end,
  },

  -- Status column plugin that provides a configurable 'statuscolumn' and click handlers.
  -- align linenumber and relativelinenumber
  {
    "luukvbaal/statuscol.nvim",
    lazy = false,
    config = function()
      local builtin = require("statuscol.builtin")
      require("statuscol").setup({
        relculright = true,
        ft_ignore = {
          "help",
          "dashboard",
          "snacks_dashboard",
          "neo-tree",
          "Trouble",
          "lazy",
          "notify",
        },
        segments = {
          -- sign
          { text = { "%s" }, click = "v:lua.ScSa" },
          -- line number
          {
            text = { builtin.lnumfunc, " " },
            condition = { true, builtin.not_empty },
            click = "v:lua.ScLa",
          },
          -- fold
          { text = { builtin.foldfunc, " " }, click = "v:lua.ScFa" },
        },
      })
    end,
  },

  -- expand/collapse (fold)
  {
    "kevinhwang91/nvim-ufo",
    dependencies = {
      "kevinhwang91/promise-async",
    },
    config = function()
      -- https://github.com/kevinhwang91/nvim-ufo#customize-fold-text
      local fold_virt_text_handler = function(virtText, lnum, endLnum, width, truncate)
        local newVirtText = {}
        local suffix = (" 󰁂 %d "):format(endLnum - lnum)
        local sufWidth = vim.fn.strdisplaywidth(suffix)
        local targetWidth = width - sufWidth
        local curWidth = 0
        for _, chunk in ipairs(virtText) do
          local chunkText = chunk[1]
          local chunkWidth = vim.fn.strdisplaywidth(chunkText)
          if targetWidth > curWidth + chunkWidth then
            table.insert(newVirtText, chunk)
          else
            chunkText = truncate(chunkText, targetWidth - curWidth)
            local hlGroup = chunk[2]
            table.insert(newVirtText, { chunkText, hlGroup })
            chunkWidth = vim.fn.strdisplaywidth(chunkText)
            -- str width returned from truncate() may less than 2nd argument, need padding
            if curWidth + chunkWidth < targetWidth then
              suffix = suffix .. (" "):rep(targetWidth - curWidth - chunkWidth)
            end
            break
          end
          curWidth = curWidth + chunkWidth
        end
        table.insert(newVirtText, { suffix, "MoreMsg" })
        return newVirtText
      end

      local ignored_filetypes = {
        lazy = true,
        snacks_dashboard = true,
      }
      local provider_selector = function(_, filetype, _)
        if ignored_filetypes[filetype] then
          return ""
        end

        return { "treesitter", "indent" }
      end

      require("ufo").setup({
        provider_selector = provider_selector,
        fold_virt_text_handler = fold_virt_text_handler,
      })
    end,
  },
}
