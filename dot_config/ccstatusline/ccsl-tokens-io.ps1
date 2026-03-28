$input | jq -r '
  def fmt:
    if . == null then "?"
    elif . >= 1000000 then "\(. / 1000000 * 10 | round / 10)M"
    elif . >= 1000 then "\(. / 1000 * 10 | round / 10)k"
    else "\(.)" end;
  .context_window // {} |
  (.total_input_tokens // null) as $in |
  (.total_output_tokens // null) as $out |
  if $in == null and $out == null then empty
  else "↑\($in | fmt) ↓\($out | fmt)" end
'
