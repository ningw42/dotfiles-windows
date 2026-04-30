$input | jq -r '
  def fmt_tokens:
    if . == null then "?"
    elif . >= 1000000 then "\(. / 1000000 * 10 | round / 10)M"
    elif . >= 1000 then "\(. / 1000 * 10 | round / 10)k"
    else "\(.)" end;
  .context_window // {} |
  (.used_percentage // 0) as $pct |
  (.context_window_size // null) as $size |
  10 as $width |
  (($pct / 100 * $width) | round) as $filled |
  ([range($width)] | map(
    if . < $filled then
      if . == 0 then "\uEE03"
      elif . == ($width - 1) then "\uEE05"
      else "\uEE04" end
    else
      if . == 0 then "\uEE00"
      elif . == ($width - 1) then "\uEE02"
      else "\uEE01" end
    end
  ) | join("")) + " \($pct)% / \($size | fmt_tokens)"
'
