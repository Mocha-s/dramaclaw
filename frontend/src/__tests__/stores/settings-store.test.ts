import { describe, expect, it } from "vitest";

import { DEFAULT_MEDIA_STORAGE_SETTINGS, useSettingsStore } from "@/stores/settingsStore";

describe("settings store migration", () => {
  it("adds MinIO defaults without losing existing media storage settings", () => {
    const migrate = useSettingsStore.persist.getOptions().migrate;
    expect(migrate).toBeTypeOf("function");

    const migrated = migrate!(
      {
        mediaStorage: {
          provider: "aliyun_oss",
          fullyManagedUpload: false,
          cloudinary: { ...DEFAULT_MEDIA_STORAGE_SETTINGS.cloudinary },
          aliyunOss: {
            ...DEFAULT_MEDIA_STORAGE_SETTINGS.aliyunOss,
            endpoint: "oss.example.com",
          },
        },
      },
      18,
    ) as { mediaStorage: typeof DEFAULT_MEDIA_STORAGE_SETTINGS };

    expect(migrated.mediaStorage.provider).toBe("aliyun_oss");
    expect(migrated.mediaStorage.aliyunOss.endpoint).toBe("oss.example.com");
    expect(migrated.mediaStorage.minio).toEqual(
      DEFAULT_MEDIA_STORAGE_SETTINGS.minio,
    );
  });
});
