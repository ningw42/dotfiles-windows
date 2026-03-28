$input | jq -r '
  .context_window // {} |
  (.used_percentage // 0) as $pct |
  10 as $width |
  (($pct / 100 * $width) | round) as $filled |
  [range($width)] | map(
    if . < $filled then
      if . == 0 then "\uEE03"
      elif . == ($width - 1) then "\uEE05"
      else "\uEE04" end
    else
      if . == 0 then "\uEE00"
      elif . == ($width - 1) then "\uEE02"
      else "\uEE01" end
    end
  ) | join("") + " \($pct)%"
'
