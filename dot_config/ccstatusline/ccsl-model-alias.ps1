$input | jq -r '
  .model // empty |
  if type == "string" then . else (.display_name // .id // "") end |
  split("/") | last |
  sub("^claude-"; "") |
  sub("-[0-9]{8}$"; "") |
  sub("\\[1m\\]$"; "")
'
