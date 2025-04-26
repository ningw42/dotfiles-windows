return {
  -- statusline: heirline
  {
    "rebelot/heirline.nvim",
    enabled = true,
    event = "VimEnter",
    config = function()
      local conditions = require("heirline.conditions")
      local utils = require("heirline.utils")
      local colors = {
        bright_bg = utils.get_highlight("Folded").bg,
        bright_fg = utils.get_highlight("Folded").fg,
        red = utils.get_highlight("DiagnosticError").fg,
        dark_red = utils.get_highlight("DiffDelete").bg,
        green = utils.get_highlight("String").fg,
        blue = utils.get_highlight("Function").fg,
        gray = utils.get_highlight("NonText").fg,
        orange = utils.get_highlight("Constant").fg,
        purple = utils.get_highlight("Statement").fg,
        cyan = utils.get_highlight("Special").fg,
        diag_warn = utils.get_highlight("DiagnosticWarn").fg,
        diag_error = utils.get_highlight("DiagnosticError").fg,
        diag_hint = utils.get_highlight("DiagnosticHint").fg,
        diag_info = utils.get_highlight("DiagnosticInfo").fg,
        git_del = utils.get_highlight("diffRemoved").fg,
        git_add = utils.get_highlight("diffAdded").fg,
        git_change = utils.get_highlight("diffChanged").fg,

        MiniIconsRed = utils.get_highlight("MiniIconsRed").fg,
        MiniIconsBlue = utils.get_highlight("MiniIconsBlue").fg,
        MiniIconsCyan = utils.get_highlight("MiniIconsCyan").fg,
        MiniIconsGrey = utils.get_highlight("MiniIconsGrey").fg,
        MiniIconsAzure = utils.get_highlight("MiniIconsAzure").fg,
        MiniIconsGreen = utils.get_highlight("MiniIconsGreen").fg,
        MiniIconsOrange = utils.get_highlight("MiniIconsOrange").fg,
        MiniIconsPurple = utils.get_highlight("MiniIconsPurple").fg,
        MiniIconsYellow = utils.get_highlight("MiniIconsYellow").fg,
      }

      local Align = { provider = "%=" }
      local Space = { provider = " " }

      local ViMode = {
        -- get vim current mode, this information will be required by the provider
        -- and the highlight functions, so we compute it only once per component
        -- evaluation and store it as a component attribute
        init = function(self)
          self.mode = vim.fn.mode(1) -- :h mode()
        end,
        -- Now we define some dictionaries to map the output of mode() to the
        -- corresponding string and color. We can put these into `static` to compute
        -- them at initialisation time.
        static = {
          mode_names = { -- change the strings if you like it vvvvverbose!
            n = "N",
            no = "N?",
            nov = "N?",
            noV = "N?",
            ["no\22"] = "N?",
            niI = "Ni",
            niR = "Nr",
            niV = "Nv",
            nt = "Nt",
            v = "V",
            vs = "Vs",
            V = "V_",
            Vs = "Vs",
            ["\22"] = "^V",
            ["\22s"] = "^V",
            s = "S",
            S = "S_",
            ["\19"] = "^S",
            i = "I",
            ic = "Ic",
            ix = "Ix",
            R = "R",
            Rc = "Rc",
            Rx = "Rx",
            Rv = "Rv",
            Rvc = "Rv",
            Rvx = "Rv",
            c = "C",
            cv = "Ex",
            r = "...",
            rm = "M",
            ["r?"] = "?",
            ["!"] = "!",
            t = "T",
          },
          mode_colors = {
            n = "red",
            i = "green",
            v = "cyan",
            V = "cyan",
            ["\22"] = "cyan",
            c = "orange",
            s = "purple",
            S = "purple",
            ["\19"] = "purple",
            R = "orange",
            r = "orange",
            ["!"] = "red",
            t = "red",
          },
        },
        -- We can now access the value of mode() that, by now, would have been
        -- computed by `init()` and use it to index our strings dictionary.
        -- note how `static` fields become just regular attributes once the
        -- component is instantiated.
        -- To be extra meticulous, we can also add some vim statusline syntax to
        -- control the padding and make sure our string is always at least 2
        -- characters long. Plus a nice Icon.
        provider = function(self)
          return "  %2(" .. self.mode_names[self.mode] .. "%) "
        end,
        -- Same goes for the highlight. Now the foreground will change according to the current mode.
        hl = function(self)
          local mode = self.mode:sub(1, 1) -- get only the first mode character
          return { fg = self.mode_colors[mode], bg = "bright_bg", bold = true }
        end,
        -- Re-evaluate the component only on ModeChanged event!
        -- Also allows the statusline to be re-evaluated when entering operator-pending mode
        update = {
          "ModeChanged",
          pattern = "*:*",
          callback = vim.schedule_wrap(function()
            vim.cmd("redrawstatus")
          end),
        },
      }

      local FileName = {
        init = function(self)
          self.filename = vim.api.nvim_buf_get_name(0)
        end,
        provider = function(self)
          -- first, trim the pattern relative to the current directory. For other
          -- options, see :h filename-modifers
          local filename = vim.fn.fnamemodify(self.filename, ":p:.")
          if filename == "" then
            return "[No Name]"
          end
          -- now, if the filename would occupy more than 1/4th of the available
          -- space, we trim the file path to its initials
          -- See Flexible Components section below for dynamic truncation
          if not conditions.width_percent_below(#filename, 0.20) then
            filename = vim.fn.pathshorten(filename)
          end
          return filename
        end,
        hl = function()
          if vim.bo.modified then
            return { fg = "cyan", bold = true }
          else
            return { fg = utils.get_highlight("Directory").fg }
          end
        end,
      }

      local FileFlags = {
        {
          condition = function()
            return vim.bo.modified
          end,
          provider = " ",
          hl = { fg = "cyan" },
        },
        {
          condition = function()
            return not vim.bo.modifiable or vim.bo.readonly
          end,
          provider = " ",
          hl = { fg = "orange" },
        },
      }

      local GitBranch = {
        condition = conditions.is_git_repo,

        init = function(self)
          self.status_dict = vim.b.gitsigns_status_dict
        end,

        hl = { fg = "orange" },

        { -- git branch name
          provider = function(self)
            return "  " .. self.status_dict.head
          end,
          hl = { bold = true },
        },
      }

      local GitFileChanges = {
        condition = conditions.is_git_repo,

        init = function(self)
          self.status_dict = vim.b.gitsigns_status_dict
        end,

        {
          provider = function(self)
            local count = self.status_dict.added or 0
            return count > 0 and ("  " .. count)
          end,
          hl = { fg = "git_add" },
        },
        {
          provider = function(self)
            local count = self.status_dict.removed or 0
            return count > 0 and ("  " .. count)
          end,
          hl = { fg = "git_del" },
        },
        {
          provider = function(self)
            local count = self.status_dict.changed or 0
            return count > 0 and ("  " .. count)
          end,
          hl = { fg = "git_change" },
        },
      }

      local FileEncoding = {
        provider = function()
          local enc = (vim.bo.fenc ~= "" and vim.bo.fenc) or vim.o.enc -- :h 'enc'
          return enc ~= "utf-8" and enc -- hide if it's utf-8
        end,
      }

      local FileFormat = {
        static = {
          symbols = {
            unix = "󰌽",
            dos = "󰍲",
            mac = "󰀵",
          },
          highlights = {
            unix = { fg = "MiniIconsCyan" },
            dos = { fg = "MiniIconsBlue" },
            mac = { fg = "MiniIconsGrey" },
          },
        },
        init = function(self)
          self.fmt = vim.bo.fileformat
          self.symbol = self.symbols[self.fmt]
          self.highlight = self.highlights[self.fmt]
        end,
        provider = function(self)
          return self.fmt ~= "unix" and self.symbol -- hide if it's unix
        end,
        hl = function(self)
          return self.highlight
        end,
      }

      local FileTypeLSP = {
        condition = conditions.lsp_attached,
        update = { "LspAttach", "LspDetach", "BufEnter" },
        static = {
          icon_provider = require("mini.icons"),
        },
        provider = function(self)
          local names = {}
          for i, server in pairs(vim.lsp.get_clients({ bufnr = 0 })) do
            table.insert(names, server.name)
          end
          local icon, _, _ = self.icon_provider.get("filetype", vim.bo.filetype)
          return icon .. "  " .. table.concat(names, " ")
        end,
        hl = function(self)
          local _, hl, _ = self.icon_provider.get("filetype", vim.bo.filetype)
          return { fg = hl, bold = true }
        end,
      }

      local WorkDir = {
        static = {
          icon_provider = require("mini.icons"),
        },
        provider = function(self)
          local cwd = vim.fn.getcwd(0)
          cwd = vim.fn.fnamemodify(cwd, ":~")
          local icon, hl, _ = self.icon_provider.get("directory", cwd)
          if not conditions.width_percent_below(#cwd, 0.2) then
            cwd = vim.fn.pathshorten(cwd)
          end
          local trail = cwd:sub(-1) == "/" and "" or "/"
          return icon .. " " .. cwd .. trail
        end,
        hl = { fg = "blue" },
      }

      -- Full nerd (with icon colors and clickable elements)!
      -- works in multi window, but does not support flexible components (yet ...)
      local Navic = {
        condition = function()
          return require("nvim-navic").is_available()
        end,
        static = {
          -- create a type highlight map
          type_hl = {
            File = "Directory",
            Module = "@include",
            Namespace = "@namespace",
            Package = "@include",
            Class = "@structure",
            Method = "@method",
            Property = "@property",
            Field = "@field",
            Constructor = "@constructor",
            Enum = "@field",
            Interface = "@type",
            Function = "@function",
            Variable = "@variable",
            Constant = "@constant",
            String = "@string",
            Number = "@number",
            Boolean = "@boolean",
            Array = "@field",
            Object = "@type",
            Key = "@keyword",
            Null = "@comment",
            EnumMember = "@field",
            Struct = "@structure",
            Event = "@keyword",
            Operator = "@operator",
            TypeParameter = "@type",
          },
          -- bit operation dark magic, see below...
          enc = function(line, col, winnr)
            return bit.bor(bit.lshift(line, 16), bit.lshift(col, 6), winnr)
          end,
          -- line: 16 bit (65535); col: 10 bit (1023); winnr: 6 bit (63)
          dec = function(c)
            local line = bit.rshift(c, 16)
            local col = bit.band(bit.rshift(c, 6), 1023)
            local winnr = bit.band(c, 63)
            return line, col, winnr
          end,
        },
        init = function(self)
          local data = require("nvim-navic").get_data() or {}
          local children = {}
          -- create a child for each level
          for i, d in ipairs(data) do
            -- encode line and column numbers into a single integer
            local pos = self.enc(d.scope.start.line, d.scope.start.character, self.winnr)
            local child = {
              {
                provider = d.icon,
                hl = self.type_hl[d.type],
              },
              {
                -- escape `%`s (elixir) and buggy default separators
                provider = d.name:gsub("%%", "%%%%"):gsub("%s*->%s*", ""),
                -- highlight icon only or location name as well
                -- hl = self.type_hl[d.type],

                on_click = {
                  -- pass the encoded position through minwid
                  minwid = pos,
                  callback = function(_, minwid)
                    -- decode
                    local line, col, winnr = self.dec(minwid)
                    vim.api.nvim_win_set_cursor(vim.fn.win_getid(winnr), { line, col })
                  end,
                  name = "heirline_navic",
                },
              },
            }
            -- add a separator only if needed
            if #data > 1 and i < #data then
              table.insert(child, {
                provider = " > ",
                hl = { fg = "bright_fg" },
              })
            end
            table.insert(children, child)
          end
          -- instantiate the new child, overwriting the previous one
          self.child = self:new(children, 1)
        end,
        -- evaluate the children containing navic components
        provider = function(self)
          return self.child:eval()
        end,
        hl = { fg = "gray" },
        update = { "BufEnter", "CursorMoved" },
      }

      local Diagnostics = {
        condition = conditions.has_diagnostics,

        init = function(self)
          self.errors = #vim.diagnostic.get(0, { severity = vim.diagnostic.severity.ERROR })
          self.warnings = #vim.diagnostic.get(0, { severity = vim.diagnostic.severity.WARN })
          self.hints = #vim.diagnostic.get(0, { severity = vim.diagnostic.severity.HINT })
          self.info = #vim.diagnostic.get(0, { severity = vim.diagnostic.severity.INFO })
        end,

        static = {
          -- Fetching custom diagnostic icons
          error_icon = vim.diagnostic.config()["signs"]["text"][vim.diagnostic.severity.ERROR],
          warn_icon = vim.diagnostic.config()["signs"]["text"][vim.diagnostic.severity.WARN],
          info_icon = vim.diagnostic.config()["signs"]["text"][vim.diagnostic.severity.INFO],
          hint_icon = vim.diagnostic.config()["signs"]["text"][vim.diagnostic.severity.HINT],
        },

        update = { "DiagnosticChanged", "BufEnter" },

        {
          provider = function(self)
            -- 0 is just another output, we can decide to print it or not!
            return self.errors > 0 and (self.error_icon .. self.errors .. " ")
          end,
          hl = { fg = "diag_error" },
        },
        {
          provider = function(self)
            return self.warnings > 0 and (self.warn_icon .. self.warnings .. " ")
          end,
          hl = { fg = "diag_warn" },
        },
        {
          provider = function(self)
            return self.info > 0 and (self.info_icon .. self.info .. " ")
          end,
          hl = { fg = "diag_info" },
        },
        {
          provider = function(self)
            return self.hints > 0 and (self.hint_icon .. self.hints)
          end,
          hl = { fg = "diag_hint" },
        },
      }

      -- We're getting minimalist here!
      local Ruler = {
        -- %l = current line number
        -- %L = number of lines in the buffer
        -- %c = column number
        -- %P = percentage through file of displayed window
        provider = " :%l/%L :%c ",
        hl = { bg = "bright_bg" },
      }

      -- assemble the final config
      local config = {
        statusline = {
          ViMode,
          Space,
          GitBranch,
          Space,
          WorkDir,
          Align,
          FileName,
          FileFlags,
          GitFileChanges,
          Align,
          Diagnostics,
          Space,
          FileTypeLSP,
          Space,
          FileEncoding,
          FileFormat,
          Space,
          Ruler,
        },
        winbar = { Navic },
      }

      -- setup heirline
      require("heirline").load_colors(colors)
      require("heirline").setup(config)
    end,
  },

  -- statusline: lualine.nvim
  {
    "nvim-lualine/lualine.nvim",
    enabled = false,
    event = "VimEnter",
    opts = {
      options = {
        icons_enabled = true,
        globalstatus = true,
        -- disable lualine for dashboard.nvim and neo-tree
        -- disabled_filetypes = { statusline = { "dashboard", "neo-tree" } },
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
          {
            "filetype",
            colored = true,
            icon_only = true,
          },
          {
            "filename",
            file_status = true,
            newfile_status = true,
            symbols = {
              modified = "●",
              readonly = "",
              unnamed = "[New]",
              newfile = "",
            },
          },
        },
        lualine_c = {
          {
            "diff",
            symbols = { added = " ", modified = " ", removed = " " },
          },
        },
        lualine_x = { "diagnostics" },
        lualine_y = {
          "encoding",
          {
            "fileformat",
            symbols = {
              unix = "󰌽",
              dos = "󰍲",
              mac = "󰀵",
            },
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
      winbar = {
        lualine_c = {
          {
            "navic",
            color_correction = nil,
            navic_opts = nil,
          },
        },
      },
      extensions = { "neo-tree", "lazy", "trouble" },
    },
  },
}
