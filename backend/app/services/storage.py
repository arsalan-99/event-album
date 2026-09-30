import logging
from typing import Optional
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from app.core.config import settings

logger = logging.getLogger(__name__)


class R2StorageService:
    def __init__(self):
        self.endpoint_url = settings.R2_ENDPOINT_URL or (
            f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
            if settings.R2_ACCOUNT_ID
            else ""
        )
        self.bucket_name = settings.R2_BUCKET_NAME
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                config=Config(signature_version="s3v4"),
                region_name="auto",
            )
        return self._client

    def ensure_cors_configured(self):
        """Ensure R2 bucket has CORS rules allowing browser direct uploads."""
        cors_config = {
            "CORSRules": [
                {
                    "AllowedHeaders": ["*"],
                    "AllowedMethods": ["GET", "PUT", "HEAD", "POST"],
                    "AllowedOrigins": ["*"],
                    "ExposeHeaders": ["*"],
                    "MaxAgeSeconds": 86400,
                }
            ]
        }
        try:
            self.client.put_bucket_cors(
                Bucket=self.bucket_name,
                CORSConfiguration=cors_config,
            )
            logger.info(f"Verified CORS configuration on R2 bucket: {self.bucket_name}")
        except Exception as e:
            logger.warning(f"Could not configure CORS on bucket {self.bucket_name}: {e}")

    def generate_presigned_put_url(
        self,
        key: str,
        content_type: Optional[str] = None,
        expires_in: int = 900,  # 15 minutes
    ) -> str:
        """
        Generate a 15-minute presigned PUT URL for direct browser upload.
        Note: We intentionally omit ContentType from Params so Content-Type is NOT
        a signed header. This prevents SignatureDoesNotMatch errors caused by
        browser MIME-type variations.
        """
        return self.client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket_name,
                "Key": key,
            },
            ExpiresIn=expires_in,
        )

    def generate_presigned_get_url(
        self,
        key: str,
        expires_in: int = 3600,  # 1 hour
    ) -> str:
        """Generate a short-lived presigned GET URL keeping bucket private."""
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket_name,
                "Key": key,
            },
            ExpiresIn=expires_in,
        )

    def object_exists(self, key: str) -> bool:
        """Check if an object exists in R2."""
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                return False
            raise

    def upload_file_bytes(
        self,
        file_bytes: bytes,
        key: str,
        content_type: str = "image/jpeg",
    ) -> str:
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
        )
        return key

    def download_file_bytes(self, key: str) -> bytes:
        response = self.client.get_object(
            Bucket=self.bucket_name,
            Key=key,
        )
        return response["Body"].read()

    def delete_file(self, key: str) -> None:
        """Delete an object from R2."""
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=key)
        except ClientError:
            pass

    def delete_files(self, keys: list[str]) -> None:
        """Batch delete objects from R2."""
        if not keys:
            return
        for i in range(0, len(keys), 1000):
            chunk = [{"Key": k} for k in keys[i : i + 1000]]
            try:
                self.client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={"Objects": chunk, "Quiet": True},
                )
            except ClientError:
                pass


storage_service = R2StorageService()
