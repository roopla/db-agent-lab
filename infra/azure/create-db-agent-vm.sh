#!/usr/bin/env bash
# =============================================================================
# create-db-agent-vm.sh - create an Ubuntu VM for the db-agent stack (Azure).
#
# Run it in Azure Cloud Shell (Bash):   bash create-db-agent-vm.sh
#
# What it does
#   1. Picks your resource group (you can't create one): uses the only one you
#      have, or shows a menu. The VM goes in that group's region.
#   2. Picks the first allowed 8 GB size available there:
#      D2s_v5 -> D2s_v4 -> D2s_v3 -> B2ms   (or DS3 v2 / 14 GB with SIZE=...)
#   3. Creates Ubuntu 24.04, 64 GB SSD, USERNAME + PASSWORD login, SSH port only.
#   4. Installs on the VM: Docker + Docker Compose, unzip, uv, tmux, git,
#      fail2ban (blocks password guessing) and 2 GB swap - then verifies them.
#   5. Prints the ssh / scp commands for the next steps.
#
# Optional settings (environment variables), e.g.  VM_NAME=agent2 bash create-db-agent-vm.sh
#   RESOURCE_GROUP   use this group instead of asking
#   LOCATION         region (default: the resource group's region)
#   VM_NAME          default: db-agent-vm
#   SIZE             force a size, e.g. Standard_DS3_v2 (4 vCPU / 14 GB)
#   ADMIN_USER       login name (else you'll be asked; default azureuser)
#   SSH_SOURCE_IP    only allow SSH from this IP (else you'll be asked)
#   AUTO_SHUTDOWN    daily shutdown time in UTC, e.g. 2300 (default: none)
# The password is always asked for interactively (never stored in a file).
# =============================================================================
set -euo pipefail

VM_NAME="${VM_NAME:-db-agent-vm}"
IMAGE="Canonical:ubuntu-24_04-lts:server:latest"
PREFERRED_SIZES=(Standard_D2s_v5 Standard_D2s_v4 Standard_D2s_v3 Standard_B2ms)
TAG="project=db-agent"
# Names Azure refuses as Linux admin usernames
RESERVED_USERS=" administrator admin user user1 test user2 test1 user3 admin1 1 123 a actuser adm admin2 aspnet backup console david guest john owner root server sql support support_388945a0 sys test2 test3 user4 user5 "

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[!] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

command -v az >/dev/null || die "Azure CLI not found. Run this in Azure Cloud Shell (Bash)."
az account show >/dev/null 2>&1 || die "Not logged in. Run: az login"

say "Subscription: $(az account show --query name -o tsv)"

# --------------------------------------------------------------- resource group
if [[ -z "${RESOURCE_GROUP:-}" ]]; then
  mapfile -t GROUPS_LIST < <(az group list --query "[].name" -o tsv | sort)
  case ${#GROUPS_LIST[@]} in
    0) die "No resource groups visible to you. Ask your admin for access to one." ;;
    1) RESOURCE_GROUP="${GROUPS_LIST[0]}"
       echo "Using your only resource group: $RESOURCE_GROUP" ;;
    *) echo "Resource groups you can use:"
       select g in "${GROUPS_LIST[@]}"; do
         [[ -n "${g:-}" ]] && RESOURCE_GROUP="$g" && break
         echo "Pick a number from the list."
       done ;;
  esac
fi
az group show -n "$RESOURCE_GROUP" >/dev/null 2>&1 \
  || die "Resource group '$RESOURCE_GROUP' not found or not accessible."
LOCATION="${LOCATION:-$(az group show -n "$RESOURCE_GROUP" --query location -o tsv)}"
echo "Resource group: $RESOURCE_GROUP   Region: $LOCATION"

# ------------------------------------------------------------- already exists?
if az vm show -g "$RESOURCE_GROUP" -n "$VM_NAME" >/dev/null 2>&1; then
  IP=$(az vm show -d -g "$RESOURCE_GROUP" -n "$VM_NAME" --query publicIps -o tsv)
  warn "VM '$VM_NAME' already exists in $RESOURCE_GROUP (public IP: ${IP:-none})."
  echo "Use VM_NAME=<other-name> to create another, or delete it first:"
  echo "  az vm delete -g $RESOURCE_GROUP -n $VM_NAME --yes"
  exit 0
fi

# ------------------------------------------------------------------- VM size
size_ok() {  # is this size offered in $LOCATION without restrictions?
  local n
  n=$(az vm list-skus -l "$LOCATION" --resource-type virtualMachines --size "$1" \
        --query "[?name=='$1' && length(restrictions)==\`0\`] | length(@)" -o tsv 2>/dev/null || echo 0)
  [[ "${n:-0}" -gt 0 ]]
}
if [[ -n "${SIZE:-}" ]]; then
  size_ok "$SIZE" || warn "$SIZE may not be available in $LOCATION; trying anyway."
else
  say "Finding an available 8 GB size in $LOCATION (takes ~30 s)"
  for s in "${PREFERRED_SIZES[@]}"; do
    if size_ok "$s"; then SIZE="$s"; break; fi
    echo "  $s: not available here"
  done
  [[ -n "${SIZE:-}" ]] || die "None of ${PREFERRED_SIZES[*]} is available in $LOCATION. Try SIZE=Standard_DS3_v2."
fi
echo "Size: $SIZE"

# ------------------------------------------------------- username + password
if [[ -z "${ADMIN_USER:-}" ]]; then
  echo
  read -r -p "VM login username [azureuser]: " ADMIN_USER || true
  ADMIN_USER="${ADMIN_USER:-azureuser}"
fi
ADMIN_USER="${ADMIN_USER,,}"
[[ "$ADMIN_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] \
  || die "Username must be lowercase letters, digits, '-' or '_' (start with a letter), max 32."
[[ "$RESERVED_USERS" != *" $ADMIN_USER "* ]] \
  || die "Azure doesn't allow the username '$ADMIN_USER'. Pick another (e.g. azureuser)."

check_password() {  # the same rules Azure CLI applies (12-72 chars, 3 of 4 kinds)
  PW="$1" U="$ADMIN_USER" python3 - <<'PYCHECK'
import os, re, sys
p, u = os.environ["PW"], os.environ["U"]
kinds = sum(bool(re.search(r, p)) for r in
            ("[a-z]", "[A-Z]", "[0-9]", r"""[ `~!@#$%^&*()=+_\[\]{}\|;:./'",<>?]"""))
if not 12 <= len(p) <= 72:
    print("must be 12-72 characters"); sys.exit(1)
if kinds < 3:
    print("needs 3 of: lowercase, uppercase, digit, symbol (note: '-' doesn't count as a symbol)"); sys.exit(1)
if u in p.lower():
    print("must not contain the username"); sys.exit(1)
PYCHECK
}
echo "Choose a password for '$ADMIN_USER' (12+ chars, 3 of: lowercase, uppercase, digit, symbol)."
while true; do
  read -r -s -p "Password: " ADMIN_PASSWORD || die "No password entered."; echo
  if ! why=$(check_password "$ADMIN_PASSWORD"); then echo "  Password $why. Try again."; continue; fi
  read -r -s -p "Repeat password: " p2 || die "No password entered."; echo
  [[ "$ADMIN_PASSWORD" == "$p2" ]] && break
  echo "  Passwords don't match. Try again."
done
unset p2

# --------------------------------------------------------- who may SSH in
if [[ -z "${SSH_SOURCE_IP+x}" ]]; then
  echo
  echo "Restrict SSH to your laptop's public IP? STRONGLY recommended with password login."
  echo "(Find your IP at https://ifconfig.me.) Enter the IP, or press Enter to allow any IP."
  read -r -p "> " SSH_SOURCE_IP || true
fi
SSH_SOURCE_IP="${SSH_SOURCE_IP// }"
if [[ -z "$SSH_SOURCE_IP" ]]; then
  warn "SSH will be open to the whole internet. fail2ban will block repeated wrong passwords,"
  warn "but limiting it to your IP is much safer (you can change it later in the NSG)."
elif [[ ! "$SSH_SOURCE_IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}(/[0-9]{1,2})?$ ]]; then
  die "'$SSH_SOURCE_IP' doesn't look like an IPv4 address (e.g. 203.0.113.7)."
fi

# ---------------------------------------------- software installed on first boot
CLOUD_INIT="$(mktemp)"
trap 'rm -f "$CLOUD_INIT"' EXIT
cat > "$CLOUD_INIT" <<EOF
#cloud-config
# Allow username/password SSH login
ssh_pwauth: true
package_update: true
packages:
  - ca-certificates
  - curl
  - unzip
  - git
  - tmux
  - jq
  - fail2ban
runcmd:
  # Docker Engine + Docker Compose plugin (official install script)
  - curl -fsSL https://get.docker.com | sh
  - systemctl enable --now docker
  - usermod -aG docker ${ADMIN_USER}
  # uv (Python project manager) for the login user
  - su - ${ADMIN_USER} -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
  # fail2ban: ban IPs after 5 failed SSH logins
  - systemctl enable --now fail2ban
  # 2 GB swap as a safety margin
  - fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  - echo '/swapfile none swap sw 0 0' >> /etc/fstab
  - touch /var/tmp/db-agent-ready
EOF

# --------------------------------------------------------------- create VM
say "Creating VM '$VM_NAME' ($SIZE, Ubuntu 24.04) - about 2 minutes"
az vm create \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --name "$VM_NAME" \
  --image "$IMAGE" \
  --size "$SIZE" \
  --authentication-type password \
  --admin-username "$ADMIN_USER" \
  --admin-password "$ADMIN_PASSWORD" \
  --os-disk-size-gb 64 \
  --storage-sku StandardSSD_LRS \
  --public-ip-sku Standard \
  --nsg-rule SSH \
  --nic-delete-option Delete \
  --os-disk-delete-option Delete \
  --custom-data "$CLOUD_INIT" \
  --tags "$TAG" \
  --output none
unset ADMIN_PASSWORD

IP=$(az vm show -d -g "$RESOURCE_GROUP" -n "$VM_NAME" --query publicIps -o tsv)
echo "Created. Public IP: $IP"

if [[ -n "$SSH_SOURCE_IP" ]]; then
  say "Allowing SSH only from $SSH_SOURCE_IP"
  az network nsg rule update -g "$RESOURCE_GROUP" --nsg-name "${VM_NAME}NSG" \
    -n default-allow-ssh --source-address-prefixes "$SSH_SOURCE_IP" --output none \
    || warn "Couldn't restrict the SSH rule; it still allows any IP."
fi

if [[ -n "${AUTO_SHUTDOWN:-}" ]]; then
  say "Daily auto-shutdown at ${AUTO_SHUTDOWN} UTC"
  az vm auto-shutdown -g "$RESOURCE_GROUP" -n "$VM_NAME" --time "$AUTO_SHUTDOWN" --output none \
    || warn "Couldn't set auto-shutdown (policy may block it)."
fi

# ------------------------------------------- wait for installs, then verify
say "Installing Docker, Docker Compose, unzip, uv, fail2ban on the VM (2-5 minutes)"
VERIFY=$(cat <<EOS
cloud-init status --wait >/dev/null 2>&1
echo "setup:          \$(test -f /var/tmp/db-agent-ready && echo complete || echo INCOMPLETE - see /var/log/cloud-init-output.log)"
echo "docker:         \$(docker --version 2>/dev/null || echo MISSING)"
echo "docker compose: \$(docker compose version 2>/dev/null || echo MISSING)"
echo "unzip:          \$(unzip -v 2>/dev/null | head -1 || echo MISSING)"
echo "uv:             \$(su - ${ADMIN_USER} -c '~/.local/bin/uv --version' 2>/dev/null || echo MISSING)"
echo "fail2ban:       \$(systemctl is-active fail2ban)"
echo "password login: \$(sshd -T 2>/dev/null | awk '/^passwordauthentication/{print \$2}')"
echo "memory:         \$(free -h | awk '/^Mem/{print \$2" total"}'), swap \$(free -h | awk '/^Swap/{print \$2}')"
EOS
)
az vm run-command invoke -g "$RESOURCE_GROUP" -n "$VM_NAME" --command-id RunShellScript \
  --scripts "$VERIFY" --query "value[0].message" -o tsv \
  | sed -n '/\[stdout\]/,/\[stderr\]/p' | grep -v '^\[std' | sed '/^$/d' \
  || warn "Couldn't read the install status; log in and run: docker --version; unzip -v"

# ------------------------------------------------------------------ summary
cat <<EOF

============================================================================
 VM ready:  $VM_NAME  ($SIZE)   IP: $IP   RG: $RESOURCE_GROUP / $LOCATION
 Login:     $ADMIN_USER  + the password you chose
============================================================================
 From your LAPTOP (you'll be asked for the password):
   1. Copy the project:  scp db-agent.zip $ADMIN_USER@$IP:~
   2. Log in:            ssh $ADMIN_USER@$IP
   3. Web UI tunnel:     ssh -L 8501:localhost:8501 $ADMIN_USER@$IP

 On the VM (Docker, unzip and uv are already installed):
   unzip db-agent.zip && cd db-agent
   bash scripts/make-env.sh && nano .env      # set OPENAI_API_KEY
   uv sync && docker compose up -d
   watch docker compose ps                    # wait for (healthy)
   uv run --env-file .env python scripts/check.py
   uv run --env-file .env python app/agent.py

 Stop paying while idle:  az vm deallocate -g $RESOURCE_GROUP -n $VM_NAME
 Start again:             az vm start -g $RESOURCE_GROUP -n $VM_NAME
 Reset the password:      az vm user update -g $RESOURCE_GROUP -n $VM_NAME -u $ADMIN_USER -p '<new password>'
 Delete everything (VM, disk, NIC go together; then IP, NSG, VNet):
   az vm delete -g $RESOURCE_GROUP -n $VM_NAME --yes
   az network public-ip delete -g $RESOURCE_GROUP -n ${VM_NAME}PublicIP
   az network nsg delete -g $RESOURCE_GROUP -n ${VM_NAME}NSG
   az network vnet delete -g $RESOURCE_GROUP -n ${VM_NAME}VNET
============================================================================
EOF
