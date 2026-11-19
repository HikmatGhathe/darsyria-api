#!/usr/bin/env bash
set -Eeuo pipefail

# Compute Engine runs this script as root on every boot. Install only missing
# packages so a routine reboot does not upgrade Docker or restart containers.
# Docker data stays in /var/lib/docker on the protected persistent boot disk.
if [[ "${EUID}" -ne 0 ]]; then
  echo "This startup script must run as root." >&2
  exit 1
fi

source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "24.04" ]]; then
  echo "This startup script requires Ubuntu 24.04." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt_options=(-o DPkg::Lock::Timeout=300 -o Acquire::Retries=5)

install_missing_packages() {
  local package status
  local -a missing_packages=()

  for package in "$@"; do
    if ! status=$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null) ||
      [[ "$status" != "install ok installed" ]]; then
      missing_packages+=("$package")
    fi
  done

  if (( ${#missing_packages[@]} > 0 )); then
    apt-get "${apt_options[@]}" -o APT::Update::Error-Mode=any update
    apt-get "${apt_options[@]}" install --yes --no-install-recommends "${missing_packages[@]}"
  fi
}

install_missing_packages ca-certificates curl git

# Docker's official Ubuntu repository uses a repository-scoped signing key.
# https://docs.docker.com/engine/install/ubuntu/#install-using-the-apt-repository
install -m 0755 -d /etc/apt/keyrings
if [[ ! -s /etc/apt/keyrings/docker.asc ]]; then
  docker_key_tmp=$(mktemp /etc/apt/keyrings/docker.asc.XXXXXX)
  trap 'rm -f "$docker_key_tmp"' EXIT
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 2 --retry-connrefused \
    --connect-timeout 15 --max-time 120 \
    https://download.docker.com/linux/ubuntu/gpg -o "$docker_key_tmp"
  chmod 0644 "$docker_key_tmp"
  mv "$docker_key_tmp" /etc/apt/keyrings/docker.asc
  trap - EXIT
fi

cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

install_missing_packages \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now containerd.service docker.service
docker --version
docker compose version
echo "Docker is ready. Deploy the application separately with sudo docker compose."
