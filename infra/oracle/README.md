# Deploy on an Oracle Cloud Always Free VM

Result: `https://<ip-with-dashes>.sslip.io` with automatic HTTPS, reviewer login preloaded, restarts on reboot.

## 1. Create the VM (once, in the Oracle console)
1. Compute, Instances, Create instance. Image: Ubuntu 24.04 (aarch64). Shape: VM.Standard.A1.Flex with 2 OCPU and 12 GB
   memory (the free allowance is up to 4 OCPU and 24 GB in total). If it says "out of capacity", retry later or pick
   another availability domain.
2. Add your SSH public key (or let Oracle generate one and download it).
3. Networking: open ingress ports 80 and 443 in the subnet security list (source 0.0.0.0/0, TCP).
4. Note the public IP.

## 2. Prepare the VM (over SSH)
```
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT && sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
git clone https://github.com/mrayyan6/gigbid && cd gigbid
```
Ubuntu images on Oracle block ports with iptables by default, so the first line matters.

## 3. Secrets (on your laptop)
```
python scripts/make_server_env.py <public-ip>
scp server.env ubuntu@<public-ip>:~/gigbid/server.env
```
`server.env` is git ignored. It copies only the keys the app needs from your local `.env`.

## 4. Start (on the VM, in the gigbid folder)
```
docker compose -f infra/oracle/docker-compose.yml --env-file server.env up -d --build
```
The first build takes 10 to 20 minutes on ARM (it bakes the embedding and reranker models). Check
`docker compose -f infra/oracle/docker-compose.yml ps` until `app` is healthy, then run from your laptop:
`python scripts/smoke_live.py https://<ip-with-dashes>.sslip.io`.

## Update after a new push
```
git pull && docker compose -f infra/oracle/docker-compose.yml --env-file server.env up -d --build
```

## Notes
- State (SQLite users, audit log) lives in the `gigbid_state` volume. Checkpoints and the queue use Neon and Upstash.
- Oracle reclaims Always Free VMs that stay idle for a long time. Point a free uptime monitor at `/api/health`.
- Reviewer password: change `REVIEWER_PASSWORD` in `.env`, rerun `make_server_env.py`, copy and restart.
