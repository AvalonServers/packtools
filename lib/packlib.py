import os
import toml
import json
import zipfile
import tempfile
import requests
import urllib.parse
import urllib.request
import subprocess
import shutil
import pathlib
from typing import Any

DOWNLOAD_ENDPOINT = "https://s3.eu-west-1.wasabisys.com/parallax-assets/data"
INSTALLER_BOOTSTRAPPER_ENDPOINT = "https://github.com/packwiz/packwiz-installer-bootstrap/releases/latest/download/packwiz-installer-bootstrap.jar"


class PackSupplementaryData:
    def __init__(self, data):
        self.series = data["series"]
        self.name = data["name"]
        self.servers = data["servers"]
    
    def slug(self) -> str:
        return f"{self.series}-{self.name}"


class ModrinthPackUploader:
    def __init__(self, slug: str, pack_root: str, token: str):
        self._slug = slug
        self._pack_root = pack_root
        self._token = token

        self._mr_slug = f"avalon-{self._slug}"
        self._mr_service = "https://api.modrinth.com/v2"
        self._mr_headers = {"Authorization": self._token}

        # read the pack metadata
        with open(f"{pack_root}/pack.toml") as f:
            self._pack = toml.load(f)
    
    def _embed_untrusted_sources(self, mrpack: str):
        """
        downloads and embeds mods from "untrusted" sources into the pack
        required for modrinth to be happy with the upload
        """
        TRUSTED_DOMAINS = ["cdn.modrinth.com", "edge.forgecdn.net", "github.com", "raw.githubusercontent.com"]

        with tempfile.TemporaryDirectory() as tmpdir:
            def download_file(url: str, path: str):
                path = os.path.join(tmpdir, path)
                os.makedirs(os.path.dirname(path), exist_ok=True)

                with requests.get(url, stream=True) as r:
                    with open(path, "wb") as f:
                        shutil.copyfileobj(r.raw, f)

            with zipfile.ZipFile(mrpack, "r") as archive:
                archive.extractall(tmpdir)
            
            with open(f"{tmpdir}/modrinth.index.json") as f:
                data = json.load(f)
            
            output_files = []
            for file in data.get("files", []):
                if len(file.get("downloads", [])) <= 0:
                    continue
                source = file["downloads"][0]
                parsed = urllib.parse.urlparse(source)
                if parsed.hostname in TRUSTED_DOMAINS:
                    output_files.append(file)
                else:
                    download_file(source, file["path"])

            data["files"] = output_files

            with open(f"{tmpdir}/modrinth.index.json", "w") as f:
                json.dump(data, f, indent=4)

            with zipfile.ZipFile(mrpack, "w") as archive:
                for f, _, fns in os.walk(tmpdir):
                    for fn in fns:
                        fp = os.path.join(f, fn)
                        archive.write(fp, os.path.relpath(fp, tmpdir))

    def _create_or_update_project(self) -> str:
        result = requests.get(
            f"{self._mr_service}/project/{self._mr_slug}",
            headers=self._mr_headers,
        )

        if "description" not in self._pack:
            raise Exception("Pack must include a description")

        fields = {
            "slug": self._mr_slug,
            "title": self._pack["name"],
            "description": self._pack["description"],
            "categories": [],
            "client_side": "required",
            "server_side": "required",
            "body": "",
            "status": "draft",
            "license_id": "lgpl-3",
            "issues_url": "https://github.com/AvalonServers/modpacks/issues",
            "source_url": "https://github.com/AvalonServers/modpacks",
            "wiki_url": "https://github.com/AvalonServers/modpacks/wiki",
            "project_type": "modpack",
            "initial_versions": [],
            "is_draft": True,
        }

        if result.status_code == 200:
            project_id = result.json()["id"]
            result = requests.patch(
                f"{self._mr_service}/project/{self._mr_slug}",
                headers=self._mr_headers,
                json=fields,
            )
            result.raise_for_status()
            return project_id
        elif result.status_code == 404:
            result = requests.post(
                f"{self._mr_service}/project",
                headers=self._mr_headers,
                files={
                    "data": json.dumps(fields),
                    "icon": (
                        "icon.png",
                        open(f"{self._pack_root}/icon.png", "rb"),
                        "image/png",
                    ),
                },
            )
            result.raise_for_status()
            return result.json()["id"]
        else:
            result.raise_for_status()

    def _create_or_update_version(self, project_id: str):
        version = self._pack["version"]
        loaders = []

        if "forge" in self._pack["versions"]:
            loaders.append("forge")
        if "fabric" in self._pack["versions"]:
            loaders.append("fabric")
        if "quilt" in self._pack["versions"]:
            loaders.append("quilt")

        fields = {
            "project_id": project_id,
            "file_parts": [f"{self._slug}.mrpack"],
            "version_number": version,
            "version_title": f"Version {version}",
            "version_body": "test",
            "dependencies": [],
            "game_versions": [self._pack["versions"]["minecraft"]],
            "loaders": loaders,
            "release_channel": "release",
            "featured": False,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            dst_name = f"{tmpdir}/{self._slug}.mrpack"
            subprocess.run(
                ["packwiz", "modrinth", "export", "-o", dst_name],
                cwd=self._pack_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            self._embed_untrusted_sources(dst_name)

            result = requests.post(
                f"{self._mr_service}/version",
                headers=self._mr_headers,
                files={
                    "data": json.dumps(fields),
                    "pack": (
                        f"{self._slug}.mrpack",
                        open(dst_name, "rb"),
                        "application/octet-stream",
                    ),
                },
            )

            print(result.json())

    def upload(self):
        project_id = self._create_or_update_project()
        self._create_or_update_version(project_id)

        # build the pack
        # with tempfile.TemporaryDirectory() as tmpdir:
        #     subprocess.run(["packwiz", "modrinth", "export", "-o", f"{tmpdir}/{self._slug}.mrpack"])

        # print(result)


class MMCPackWriter:
    def __init__(
        self,
        slug: str,
        pack_root: str,
        endpoint_override: str = None,
        is_unix_development: bool = False,
    ):
        if not os.path.isdir(pack_root):
            raise Exception("The specified pack does not exist")

        self._slug = slug
        self._pack_root = pack_root
        self._is_unix_development = is_unix_development

        if endpoint_override is not None:
            self._pack_meta_url = endpoint_override
        else:
            self._pack_meta_url = DOWNLOAD_ENDPOINT
            for pack_comp in self._slug.split("-"):
                self._pack_meta_url = f"{self._pack_meta_url}/{pack_comp}"
            self._pack_meta_url = f"{self._pack_meta_url}/pack.toml"

        # read the pack metadata
        with open(f"{pack_root}/pack.toml") as f:
            self._pack = toml.load(f)

    def _write_mmc_pack_json(self, output: str):
        components = [
            {
                "important": True,
                "uid": "net.minecraft",
                "version": self._pack["versions"]["minecraft"],
            }
        ]

        # add the modloader
        if "forge" in self._pack["versions"]:
            components.append(
                {
                    "uid": "net.minecraftforge",
                    "version": self._pack["versions"]["forge"],
                }
            )
        elif "fabric" in self._pack["versions"]:
            components.append(
                {
                    "uid": "net.fabricmc.fabric-loader",
                    "version": self._pack["versions"]["fabric"],
                }
            )
        elif "quilt" in self._pack["versions"]:
            components.append(
                {
                    "uid": "org.quiltmc.quilt-loader",
                    "version": self._pack["versions"]["quilt"],
                }
            )

        result = {"components": components, "formatVersion": 1}

        with open(output, "w") as f:
            json.dump(result, f, indent=4)

    def _write_instance_cfg_ini(self, output: str, config: dict):
        prelaunch_command = f'"$INST_JAVA" -jar packwiz-installer-bootstrap.jar {self._pack_meta_url}'
        if self._is_unix_development:
            prelaunch_command = f'bash ./developer-prelaunch.sh {self._pack_meta_url}'

        attributes = {
            "InstanceType": "OneSix",
            "OverrideCommands": True,
            "PreLaunchCommand": prelaunch_command,
            "name": self._pack["name"],
        }

        if os.path.exists(f"{self._pack_root}/icon.png"):
            attributes["iconKey"] = self._slug

        attributes = {**attributes, **config}

        config = ""
        for k, v in attributes.items():
            if isinstance(v, bool):
                v = str.lower(str(v))
            config = config + f"{k}={v}\n"
        config = config.strip()

        with open(output, "w") as f:
            f.write(config)

    def write(self, output: str, config: dict = {}):
        """
        Writes the pack to the specified output directory
        """

        self._write_mmc_pack_json(f"{output}/mmc-pack.json")
        self._write_instance_cfg_ini(f"{output}/instance.cfg", config)

        data_dir = pathlib.Path(__file__).parent.resolve().parent.joinpath("data")
        def copy_data_file(file: str):
            shutil.copyfile(f"{data_dir}/{file}", f"{output}/.minecraft/{file}")

        # copy the icon
        icon_path = f"{self._pack_root}/icon.png"
        if os.path.exists(icon_path):
            shutil.copyfile(icon_path, f"{output}/{self._slug}.png")
        
        # create minecraft dir
        os.mkdir(f"{output}/.minecraft")
        
        # copy developer utilities
        if self._is_unix_development:
            copy_data_file("developer-prelaunch.sh")
            copy_data_file("fractioniser-scanner.jar")

        # download the launcher boot strapper
        urllib.request.urlretrieve(
            INSTALLER_BOOTSTRAPPER_ENDPOINT,
            f"{output}/.minecraft/packwiz-installer-bootstrap.jar",
        )

def read_pack_supplementary_data(root: str) -> PackSupplementaryData:
    with open(f"{root}/extra.toml") as f:
        data = toml.load(f)
    return PackSupplementaryData(data)
