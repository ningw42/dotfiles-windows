@echo off
rem Lazygit prepends the pane width before Git's external-diff arguments.
set "width=%~1"
shift
set "old=%~2"
set "new=%~5"
set "target=%~1"
set "old=%old:\=/%"
set "new=%new:\=/%"

git --no-pager diff --no-index --no-ext-diff "%old%" "%new%" | ^
perl -pe "s|\Q%old%\E|%target%|g;s|\Q%new%\E|%target%|g" | ^
delta --paging=never --width=%width% --hyperlinks --hyperlinks-file-link-format="lazygit-edit://{path}:{line}"
