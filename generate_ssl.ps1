# Generate self-signed SSL certificates for HTTPS
# Run this on your Windows Server to create certificates

# Create SSL directory if it doesn't exist
New-Item -ItemType Directory -Force -Path "ssl"

# Generate private key
openssl genrsa -out ssl/checkin.solidground.co.za.key 2048

# Generate certificate signing request
openssl req -new -key ssl/checkin.solidground.co.za.key -out ssl/checkin.solidground.co.za.csr -subj "/C=ZA/ST=Gauteng/L=JHB/O=Solid Ground Church/CN=checkin.solidground.co.za"

# Generate self-signed certificate (valid for 365 days)
openssl x509 -req -days 365 -in ssl/checkin.solidground.co.za.csr -signkey ssl/checkin.solidground.co.za.key -out ssl/checkin.solidground.co.za.crt

Write-Host "SSL certificates generated successfully!"
Write-Host "Files created:"
Write-Host "  - ssl/checkin.solidground.co.za.key (private key)"
Write-Host "  - ssl/checkin.solidground.co.za.crt (certificate)"
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Copy these files to your server: S:\Docker\KidsAttendanceTracker\ssl\"
Write-Host "2. Update docker-compose.yml to mount the SSL directory"
Write-Host "3. Add nginx service to docker-compose.yml"
