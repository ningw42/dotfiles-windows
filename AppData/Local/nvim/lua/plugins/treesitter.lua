return {
  {
    "nvim-treesitter/nvim-treesitter-textobjects",
    branch = "main",
    version = false,
  },

  {
    "nvim-treesitter/nvim-treesitter",
    branch = "main",
    version = false, -- last release is way too old and doesn't work on Windows
    build = ":TSUpdate",
    dependencies = {
      "nvim-treesitter/nvim-treesitter-textobjects",
      "nvim-treesitter/nvim-treesitter-context",
    },
    opts = {
      languages = {
        "bash",
        "beancount",
        "c",
        "csv",
        "diff",
        "dockerfile",
        "fish",
        "git_config",
        "git_rebase",
        "gitattributes",
        "gitcommit",
        "gitignore",
        "go",
        "gomod",
        "gosum",
        "gotmpl",
        "gpg",
        "html",
        "ini",
        "javascript",
        "jinja",
        "jinja_inline",
        "jq",
        "json",
        "jsonc",
        "kdl",
        "latex",
        "kusto",
        "lua",
        "luadoc",
        "luap",
        "make",
        "markdown",
        "markdown_inline",
        "nix",
        "powershell",
        "proto",
        "python",
        "query",
        "regex",
        "ron",
        "rust",
        "sql",
        "ssh_config",
        "tera",
        "toml",
        "typst",
        "vim",
        "vimdoc",
        "xml",
        "yaml",
      },
    },
    config = function(_, opts)
      require("nvim-treesitter").setup({
        install_dir = vim.fs.joinpath(vim.fn.stdpath("data"), "site")
      })
      require("nvim-treesitter").install(opts.languages)

      -- gotmpl dialect setup: dynamically inject target language highlighting
      -- into .tmpl files (e.g. config.yaml.tmpl gets both gotmpl + yaml).
      -- Mirrors the upstream "helm" dialect: same parser, different queries.
      local data_site = vim.fs.joinpath(vim.fn.stdpath("data"), "site")
      local gotmpl_parser = vim.fs.joinpath(data_site, "parser", "gotmpl.so")
      local query_base = vim.fs.joinpath(data_site, "queries")
      local registered_dialects = {}

      local function register_gotmpl_dialect(lang)
        local dialect = "gotmpl_" .. lang
        if registered_dialects[dialect] then
          return dialect
        end

        local ok, ret = pcall(vim.treesitter.language.add, dialect, {
          path = gotmpl_parser,
          symbol_name = "gotmpl",
        })
        if not ok or not ret then return nil end

        -- Create query dir with `; inherits: gotmpl` so that treesitter's
        -- native query resolution handles after/queries, extends, and
        -- runtimepath precedence automatically.
        local dir = query_base .. "/" .. dialect
        vim.fn.mkdir(dir, "p")

        local function write_query(name, extra)
          local f = io.open(dir .. "/" .. name .. ".scm", "w")
          if not f then return end
          f:write("; inherits: gotmpl\n")
          if extra then f:write("\n" .. extra) end
          f:close()
        end

        write_query("highlights")
        write_query("injections",
          '((text) @injection.content\n'
          .. '  (#set! injection.language "' .. lang .. '")\n'
          .. '  (#set! injection.combined))\n')
        write_query("locals")
        write_query("folds")

        registered_dialects[dialect] = true
        return dialect
      end

      vim.filetype.add({
        pattern = {
          [".*%.tmpl"] = function(path)
            local basename = vim.fs.basename(path)
            local sub_ext = basename:match("%.([^.]+)%.tmpl$")
            if not sub_ext then return "gotmpl" end

            local ft = vim.filetype.match({ filename = "f." .. sub_ext })
            if not ft then return "gotmpl" end
            local lang = vim.treesitter.language.get_lang(ft) or ft

            local ok, ret = pcall(vim.treesitter.language.add, lang)
            if not ok or not ret then return "gotmpl" end

            return register_gotmpl_dialect(lang) or "gotmpl"
          end,
        },
      })

      vim.api.nvim_create_autocmd("FileType", {
        pattern = "gotmpl*",
        callback = function(ev)
          vim.treesitter.start(ev.buf)
        end,
      })
    end,
  },
}
