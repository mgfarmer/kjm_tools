-- Pull in the wezterm API
local wezterm = require 'wezterm'
local mux = wezterm.mux
local projects = require 'projects'
local appearance = require 'appearance'
local act = wezterm.action

-- This will hold the configuration.
local config = wezterm.config_builder()

-- config.window_decorations = 'RESIZE'

config.initial_rows = 50
config.initial_cols = 132

config.font = wezterm.font 'JetBrains Mono'
config.font_size = 14

config.window_background_opacity = 0.85
config.color_scheme = 'Builtin Dark'

config.scrollback_lines = 10000

config.launch_menu = {
  {
    args = { 'htop' },
  },
}

config.leader = { key = 'w', mods = 'CTRL', timeout_milliseconds = 1000 }

config.keys = {
  -- paste from the clipboard
  { key = 'V', mods = 'CTRL', action = act.PasteFrom 'Clipboard' },

  -- paste from the primary selection
  -- { key = 'V', mods = 'CTRL', action = act.PasteFrom 'PrimarySelection' },

  {
    key = 'w',
    mods = 'LEADER',
    -- Present in to our project picker
    action = projects.choose_project(),
  },
  {
    key = 'f',
    mods = 'LEADER',
    -- Present a list of existing workspaces
    action = wezterm.action.ShowLauncherArgs { flags = 'FUZZY|WORKSPACES' },
  },
  {
    key = 'u',
    mods = 'LEADER',
    action = wezterm.action.SwitchToWorkspace { name = 'gyrfalcon-ui' },
  },
  {
    key = 'c',
    mods = 'LEADER',
    action = wezterm.action.SwitchToWorkspace { name = 'gyrfalcon-cloud' },
  },
  {
    key = 't',
    mods = 'LEADER',
    action = wezterm.action.SwitchToWorkspace { name = 'gyrfalcon-tools' },
  },
  {
    key = '\\',
    mods = 'LEADER',
    action = wezterm.action.SplitHorizontal { domain = 'CurrentPaneDomain' },
  },
  {
    key = '-',
    mods = 'LEADER',
    action = wezterm.action.SplitVertical { domain = 'CurrentPaneDomain' },
  },
  { key = '<', mods = 'CTRL|SHIFT', action = act.SwitchWorkspaceRelative(1) },
  { key = '>', mods = 'CTRL|SHIFT', action = act.SwitchWorkspaceRelative(-1) },
}

local function createWorkspace(folder)
  local name = folder:match( "([^/]+)$" )
  local project_dir = wezterm.home_dir .. folder
  local tab, pane1, window = mux.spawn_window {
    workspace = name,
    cwd = project_dir,
    args = args,
  }
  local pane2 = pane1:split {
    direction = 'Top', 
    size = 0.33,
    cwd = project_dir,
  }
  local pane2 = pane1:split {
    direction = 'Top', 
    size = 0.33,
    cwd = project_dir,
  }

end

wezterm.on('gui-startup', function(cmd)
  -- allow `wezterm start -- something` to affect what we spawn
  -- in our initial window
  local args = {}
  if cmd then
    args = cmd.args
  end

  createWorkspace('/git/gyrfalcon-ui')
  createWorkspace('/git/gyrfalcon-tools')
  createWorkspace('/git/gyrfalcon-cloud')
  createWorkspace('/git/gyrfalcon-cdk')

end)

local function segments_for_right_status(window)
  return {
    window:active_workspace(),
    wezterm.strftime('%H:%M'),
  }
end

wezterm.on('update-status', function(window, pane)
  local date = wezterm.strftime '%Y-%m-%d %H:%M:%S'
  local SOLID_LEFT_ARROW = utf8.char(0xe0b2)
  local segments = segments_for_right_status(window)

  local color_scheme = window:effective_config().resolved_palette
  -- Note the use of wezterm.color.parse here, this returns
  -- a Color object, which comes with functionality for lightening
  -- or darkening the colour (amongst other things).

  print(window:effective_config())

  local bg = wezterm.color.parse(color_scheme.background)
  local fg = color_scheme.foreground
  local gradient_to, gradient_from = bg
  if appearance.is_dark() then
    gradient_from = gradient_to:lighten(0.2)
  else
    gradient_from = gradient_to:darken(0.2)
  end
  local gradient = wezterm.color.gradient(
    {
      orientation = 'Horizontal',
      colors = { gradient_from, gradient_to },
    },
    #segments -- only gives us as many colours as we have segments.
  )

  local elements = {}

  for i, seg in ipairs(segments) do
    local is_first = i == 1

    if is_first then
      table.insert(elements, { Background = { Color = 'none' } })
    end
    table.insert(elements, { Foreground = { Color = gradient[i] } })
    table.insert(elements, { Text = SOLID_LEFT_ARROW })

    table.insert(elements, { Foreground = { Color = fg } })
    table.insert(elements, { Background = { Color = gradient[i] } })
    table.insert(elements, { Text = ' ' .. seg .. ' ' })
  end

  window:set_right_status(wezterm.format(elements))
end)

return config

