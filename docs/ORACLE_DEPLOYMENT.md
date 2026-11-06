# Oracle Cloud deployment and operations

## Verified deployment — November 6, 2026

External requests from the administrator's Windows computer returned the homepage, healthy status, and the expected release metadata.

| Setting | Value |
|---|---|
| Compute shape | VM.Standard.E2.1.Micro, AMD64, Always Free eligible |
| OS | Ubuntu 24.04 |
| VCN / subnet | docker-cicd-vcn / docker-cicd-public |
| Public IP | 129.153.29.123 — ephemeral |
| App | http://129.153.29.123/ |
| Health | http://129.153.29.123/health |
| Release metadata | http://129.153.29.123/api/info |
| Container | docker-cicd-app |
| Host / container port | 80 / 8000 |
| Deployed commit | b734d13caeda78f9a227f701ca92cc3cc60bcad5 |

The current image is `ghcr.io/bo-giles-projects/docker-cicd-app:sha-b734d13caeda78f9a227f701ca92cc3cc60bcad5`. Its version was verified against the public API. Later documentation merges may publish newer images without updating this VM.

## Cloud and networking setup

Use an Always Free-eligible Ubuntu image and AMD VM.Standard.E2.1.Micro shape in the account's home region, within its remaining compute and storage allowances. Capacity is subject to availability; idle Always Free instances may be reclaimed. Review current limits in the Console.

The VM needs a public subnet, an internet-gateway route, a public IPv4 address, and rules allowing the desired traffic. This deployment uses a stateful TCP ingress rule with source `0.0.0.0/0`, any source port, and destination port `80`. SSH uses port 22; limit permitted source addresses to the administrator's IP where practical.

The create-instance form disabled public-IP assignment while creating a new public subnet. After VM creation, an ephemeral public IP was assigned using:

Instance → Networking → primary VNIC → IP administration → primary private IP → Edit → Ephemeral public IP.

An ephemeral IP can change if its assignment is deleted or the instance is replaced. Update the documentation's URLs when that happens.

## SSH from Windows

Save the private key outside this repository. For this deployment, PowerShell connects using:

```powershell
ssh -i "$env:USERPROFILE\.ssh\ssh-key-2026-11-06.key" ubuntu@129.153.29.123
```

The command refers to a local key file; this repository does not contain the private key.

## Install Docker on the Ubuntu VM

These commands use Ubuntu's Canonical-maintained Docker package:

```bash
sudo apt update
sudo apt install -y docker.io
sudo systemctl enable --now docker
sudo docker run --rm hello-world
```

## Run the published release

Run these commands inside the Ubuntu SSH session on a server where the application container does not already exist:

```bash
APP_IMAGE="ghcr.io/bo-giles-projects/docker-cicd-app:sha-b734d13caeda78f9a227f701ca92cc3cc60bcad5"
sudo docker pull "$APP_IMAGE"
sudo docker run -d \
  --name docker-cicd-app \
  --restart unless-stopped \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  -p 80:8000 \
  "$APP_IMAGE"
```

The restart policy restarts the container after a process exit or host reboot when Docker starts, unless it was deliberately stopped. An unhealthy status alone does not trigger a restart.

## Verify the deployment

Run on the VM:

```bash
curl -fsS --max-time 10 http://127.0.0.1/health
curl -fsS --max-time 10 http://127.0.0.1/api/info
sudo docker ps --filter name=docker-cicd-app
sudo docker inspect --format '{{.State.Health.Status}}' docker-cicd-app
sudo docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' docker-cicd-app
```

Expected health: `{"status":"ok"}`. Expected service: `docker-cicd-app`. The version must match the selected image's commit SHA; the initial deployment's SHA is recorded above. After startup the container should become `healthy` with restart policy `unless-stopped`.

Also open the public homepage and health endpoint from a separate computer. This checks the public network path as well as the application.

## Logs and restart

```bash
sudo docker logs --tail 50 docker-cicd-app
sudo docker restart docker-cicd-app
```

## Manual updates and rollback

GitHub Actions tests and publishes images on pushes to main. Updating the VM is a separate manual operation. To select a later release, replace the image tag in the release section with an actual published `sha-<commit>` tag.

1. Record the current image for rollback:

   ```bash
   sudo docker inspect --format '{{.Config.Image}}' docker-cicd-app
   ```

2. Set `APP_IMAGE` to the intended published tag and successfully pull it **before** stopping the running app.

3. Replace only the application container:

   ```bash
   sudo docker stop docker-cicd-app
   sudo docker rm docker-cicd-app
   ```

4. Repeat the `docker run` command from the release section with the selected image.
5. Verify health, service, and commit version locally and externally.

Replacement briefly interrupts service. To roll back, repeat these steps using the image tag recorded in step 1. This demo has no persistent application database or data volume.

## Troubleshooting

| Symptom | Checks |
|---|---|
| Local health check fails | Container status, logs, and port mapping from host 80 to container 8000. |
| Local health works, public browser times out | Public IP, associated subnet security list, internet-gateway route, and host firewall. |
| Browser attempts HTTPS | Use the explicit http:// URL for this current HTTP deployment. |
| Wrong version | Inspect the running image tag and compare /api/info with the intended commit. |
| GHCR pull denied | Check image visibility or authenticate with read-only package access. Keep tokens outside documentation. |
| Unhealthy container | Inspect container logs and health-check results before changing network rules. |

## Next enhancements

- HTTPS with a domain and reverse proxy.
- Automated VM deployment with health verification and rollback.
- External uptime monitoring.

## References

- [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [Oracle public IP addresses](https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/managingpublicIPs.htm)
- [Oracle security lists](https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/securitylists.htm)
- [Ubuntu Docker administration](https://ubuntu.com/server/docs/how-to/containers/docker-for-system-admins/)
