# Shop POC Launcher
Launch the whole SHOP_POC dev stack with one single command (or alias) and runs the whole SHOP_POC dev stack in a `tmux` session.
## Run
The script is called `launch-shop-poc-stack.sh` and can be run with the following command:
```bash
./launch-shop-poc-stack.sh [flags]
```
This script assumes its located in `~/Projects/.Launch/`
### Flags
* `-e` → edit mode (`shop-edit` on :3000, shop-poc → :3001)
* `-ou` → run WFO UI
* `-fl` → force local stack (ignore shop-poc `NEXT_PUBLIC_ENVIRONMENT_NAME` env)

## Services
* shop-poc
* shop-edit (opt)
* shop-backend (local)
* WFO Formatics (opt)
* WFO UI (opt, requires WFO-formatics)

## Behavior
* Missing `wfo-formatics` → skipped + disables UI
* `shop-edit` always starts first → owns :3000 (Because of login redirect)

## ⚠ Formatics CORS
If UI can't reach backend, ensure: localhost:3003 is added to the CORS list.

## Config (`~/Projects/.Launch/.env`)

```.dotenv
PROJECTS_DIR=$HOME/Projects

SHOP_POC_DIR=$PROJECTS_DIR/shop-poc
SHOP_EDIT_DIR=$PROJECTS_DIR/shop-edit
SHOP_BACKEND_DIR=$PROJECTS_DIR/shop-backend

WFO_FORMATICS_DIR=$PROJECTS_DIR/wfo-backend-formatics
WFO_UI_DIR=$PROJECTS_DIR/orchestrator-ui-library

SESSION=shop-poc-stack
```
## ⚡ Aliases
You can add the following aliases to your `.bashrc` or `.zshrc` to launch the stack with a single command.
```bash
# Launch POC
alias lpoc="~/Projects/.Launch/launch-shop-poc-stack.sh -eu -fl"
# Launch Small POC
alias lspoc="~/Projects/.Launch/launch-shop-poc-stack.sh"
# Launch Edit POC
alias lepoc="~/Projects/.Launch/launch-shop-poc-stack.sh -e -ou -fl"
```
## Req
tmux, node, npm/yarn
