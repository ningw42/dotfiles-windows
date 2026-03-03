--==================--
-- Everforest Theme --
--==================--

local background_colors = {
  dark = {
    hard = {
      bg_dim = "#1e2326",
      bg0 = "#272e33",
      bg1 = "#2e383c",
      bg2 = "#374145",
      bg3 = "#414b50",
      bg4 = "#495156",
      bg5 = "#4f5b58",
      bg_visual = "#493b40",
      bg_red = "#4c3743",
      bg_green = "#3c4841",
      bg_blue = "#384b55",
      bg_yellow = "#45443c",
    },
    medium = {
      bg_dim = "#232a2e",
      bg0 = "#2d353b",
      bg1 = "#343f44",
      bg2 = "#3d484d",
      bg3 = "#475258",
      bg4 = "#4f585e",
      bg5 = "#56635f",
      bg_visual = "#514045",
      bg_red = "#543a48",
      bg_green = "#425047",
      bg_blue = "#3a515d",
      bg_yellow = "#4d4c43",
    },
    soft = {
      bg_dim = "#293136",
      bg0 = "#333c43",
      bg1 = "#3a464c",
      bg2 = "#434f55",
      bg3 = "#4d5960",
      bg4 = "#555f66",
      bg5 = "#5d6b66",
      bg_visual = "#59464c",
      bg_red = "#5c3f4f",
      bg_green = "#48584e",
      bg_blue = "#3f5865",
      bg_yellow = "#55544a",
    },
  },
  light = {
    hard = {
      bg_dim = "#f2efdf",
      bg0 = "#fffbef",
      bg1 = "#f8f5e4",
      bg2 = "#f2efdf",
      bg3 = "#edeada",
      bg4 = "#e8e5d5",
      bg5 = "#bec5b2",
      bg_visual = "#f0f2d4",
      bg_red = "#ffe7de",
      bg_green = "#f3f5d9",
      bg_blue = "#ecf5ed",
      bg_yellow = "#fef2d5",
    },
    medium = {
      bg_dim = "#efebd4",
      bg0 = "#fdf6e3",
      bg1 = "#f4f0d9",
      bg2 = "#efebd4",
      bg3 = "#e6e2cc",
      bg4 = "#e0dcc7",
      bg5 = "#bdc3af",
      bg_visual = "#eaedc8",
      bg_red = "#fbe3da",
      bg_green = "#f0f1d2",
      bg_blue = "#e9f0e9",
      bg_yellow = "#faedcd",
    },
    soft = {
      bg_dim = "#e5dfc5",
      bg0 = "#f3ead3",
      bg1 = "#eae4ca",
      bg2 = "#e5dfc5",
      bg3 = "#ddd8be",
      bg4 = "#d8d3ba",
      bg5 = "#b9c0ab",
      bg_visual = "#e1e4bd",
      bg_red = "#f4dbd0",
      bg_green = "#e5e6c5",
      bg_blue = "#e1e7dd",
      bg_yellow = "#f1e4c5",
    },
  },
}

local foreground_colors = {
  dark = {
    fg = "#d3c6aa",
    red = "#e67e80",
    orange = "#e69875",
    yellow = "#dbbc7f",
    green = "#a7c080",
    aqua = "#83c092",
    blue = "#7fbbb3",
    purple = "#d699b6",
    grey0 = "#7a8478",
    grey1 = "#859289",
    grey2 = "#9da9a0",
    statusline1 = "#a7c080",
    statusline2 = "#d3c6aa",
    statusline3 = "#e67e80",
  },
  light = {
    fg = "#5c6a72",
    red = "#f85552",
    orange = "#f57d26",
    yellow = "#dfa000",
    green = "#8da101",
    aqua = "#35a77c",
    blue = "#3a94c5",
    purple = "#df69ba",
    grey0 = "#a6b0a0",
    grey1 = "#939f91",
    grey2 = "#829181",
    statusline1 = "#93b259",
    statusline2 = "#708089",
    statusline3 = "#e66868",
  },
}

--- Gets the Everforest theme.
--- @class EverforestOptions
--- @field background string Background of the theme: "dark" or "light".
--- @field constrast string Constrast of the theme: "hard", "medium" or "soft".
--- @return table theme Used in Yatline.
local function everforest_theme(opts)
  local background = opts["background"] or "dark"
  local constrast = opts["constrast"] or "medium"
  local foreground_palette = foreground_colors[background] or foreground_colors["dark"]
  local background_palette = background_colors[background][constrast] or background_colors["dark"]["medium"]

  -- assemble the complete color palette
  local palette = {}
  for name, color in pairs(foreground_palette) do
    palette[name] = color
  end

  for name, color in pairs(background_palette) do
    palette[name] = color
  end

  return {
    -- yatline
    section_separator_open = "",
    section_separator_close = "",

    inverse_separator_open = "",
    inverse_separator_close = "",

    part_separator_open = "",
    part_separator_close = "",

    style_a = {
      fg = palette.bg_dim,
      bg_mode = {
        normal = palette.blue,
        select = palette.purple,
        un_set = palette.red,
      },
    },
    style_b = { bg = palette.bg1, fg = palette.fg },
    style_c = { bg = palette.bg_dim, fg = palette.fg },

    permissions_t_fg = palette.green,
    permissions_r_fg = palette.yellow,
    permissions_w_fg = palette.red,
    permissions_x_fg = palette.blue,
    permissions_s_fg = palette.purple,

    selected = { icon = "󰻭", fg = palette.yellow },
    copied = { icon = "", fg = palette.green },
    cut = { icon = "", fg = palette.red },

    total = { icon = "", fg = palette.yellow },
    succ = { icon = "", fg = palette.green },
    fail = { icon = "", fg = palette.red },
    found = { icon = "", fg = palette.blue },
    processed = { icon = "", fg = palette.green },

    -- yatline-githead
    prefix_color = palette.grey1,
    branch_color = palette.blue,
    commit_color = palette.purple,
    behind_color = palette.yellow,
    ahead_color = palette.green,
    stashes_color = palette.red,
    state_color = palette.maroon,
    staged_color = palette.aqua,
    unstaged_color = palette.orange,
    untracked_color = palette.yellow,
  }
end

return {
  setup = function(_, opts)
    opts = opts or {
      background = "dark",
      constrast = "medium",
    }

    return everforest_theme(opts)
  end,
}
