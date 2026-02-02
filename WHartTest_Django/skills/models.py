import logging
import os
import stat
import zipfile
import yaml
import shutil
from pathlib import Path, PurePosixPath
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from projects.models import Project

logger = logging.getLogger(__name__)


def skill_upload_path(instance, filename):
    """Skill 文件上传路径"""
    return f'skills/{instance.project.id}/{instance.id}/{filename}'


class Skill(models.Model):
    """
    Skill 模型，存储用户上传的 Agent Skill
    """
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='skills',
        verbose_name=_('所属项目')
    )
    creator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_skills',
        verbose_name=_('创建人')
    )
    name = models.CharField(
        _('Skill 名称'),
        max_length=255,
        help_text='Skill 的唯一标识名称'
    )
    description = models.TextField(
        _('Skill 描述'),
        help_text='描述 Skill 的功能和使用场景'
    )
    skill_content = models.TextField(
        _('SKILL.md 内容'),
        blank=True,
        help_text='SKILL.md 文件的完整内容'
    )
    skill_path = models.CharField(
        _('Skill 存储路径'),
        max_length=500,
        blank=True,
        help_text='Skill 文件解压后的存储路径'
    )
    is_active = models.BooleanField(
        _('是否启用'),
        default=True
    )
    created_at = models.DateTimeField(_('创建时间'), auto_now_add=True)
    updated_at = models.DateTimeField(_('更新时间'), auto_now=True)

    class Meta:
        verbose_name = _('Skill')
        verbose_name_plural = _('Skills')
        ordering = ['-created_at']
        unique_together = ('project', 'name')

    def __str__(self):
        return f"{self.name} ({self.project.name})"

    def get_full_path(self):
        """获取 Skill 的完整文件系统路径（始终返回绝对路径）"""
        from django.conf import settings
        if self.skill_path:
            path = os.path.join(settings.MEDIA_ROOT, self.skill_path)
            return os.path.abspath(path)
        return None

    def get_script_path(self):
        """获取可执行脚本路径（支持 .py 和 .js）"""
        full_path = self.get_full_path()
        if not full_path:
            return None

        for root, dirs, files in os.walk(full_path):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', 'node_modules')]
            for f in files:
                if f.startswith('__'):
                    continue
                if f.endswith('.py') or f.endswith('.js'):
                    return os.path.join(root, f)
        return None

    @staticmethod
    def _safe_extract_zip(
        zf: zipfile.ZipFile,
        dest_dir: str,
        *,
        max_files: int = 2000,
        max_total_size: int = 50 * 1024 * 1024,
    ) -> None:
        """安全解压 zip，防止 Zip Slip / 超量解压 / 符号链接"""
        dest_path = Path(dest_dir).resolve(strict=False)
        file_count = 0
        total_size = 0

        for info in zf.infolist():
            name = (info.filename or "").replace("\\", "/")

            if not name or name.endswith("/"):
                continue

            file_count += 1
            if file_count > max_files:
                raise ValidationError("zip 文件包含过多文件")

            total_size += int(getattr(info, "file_size", 0) or 0)
            if total_size > max_total_size:
                raise ValidationError("zip 解压后总大小超出限制")

            posix = PurePosixPath(name)
            if posix.is_absolute() or any(part == ".." for part in posix.parts):
                raise ValidationError("zip 文件包含非法路径")
            if posix.parts and ":" in posix.parts[0]:
                raise ValidationError("zip 文件包含非法路径")

            mode = (info.external_attr or 0) >> 16
            if stat.S_ISLNK(mode):
                raise ValidationError("zip 文件包含不支持的符号链接")

            target_path = (dest_path / Path(*posix.parts)).resolve(strict=False)
            try:
                if os.path.commonpath([str(dest_path), str(target_path)]) != str(dest_path):
                    raise ValidationError("zip 文件包含非法路径")
            except ValueError:
                raise ValidationError("zip 文件包含非法路径")

            zf.extract(info, str(dest_path))

    @classmethod
    def parse_skill_md(cls, content: str) -> dict:
        """
        解析 SKILL.md 内容，提取 YAML frontmatter

        Returns:
            dict: {'name': ..., 'description': ..., 'body': ...}
        """
        if not content.startswith('---'):
            raise ValidationError('SKILL.md 必须以 YAML frontmatter 开头 (---)')

        parts = content.split('---', 2)
        if len(parts) < 3:
            raise ValidationError('SKILL.md 格式无效，缺少 YAML frontmatter 结束标记')

        try:
            frontmatter = yaml.safe_load(parts[1])
        except yaml.YAMLError as e:
            raise ValidationError(f'YAML frontmatter 解析失败: {e}')

        if not frontmatter:
            raise ValidationError('YAML frontmatter 为空')

        if not isinstance(frontmatter, dict):
            raise ValidationError('YAML frontmatter 必须是对象 (mapping)')

        raw_name = frontmatter.get('name', '')
        raw_description = frontmatter.get('description', '')
        if not isinstance(raw_name, str) or not isinstance(raw_description, str):
            raise ValidationError('SKILL.md 的 name/description 必须是字符串')

        name = raw_name.strip()
        description = raw_description.strip()

        if not name:
            raise ValidationError('SKILL.md 缺少 name 字段')
        if not description:
            raise ValidationError('SKILL.md 缺少 description 字段')

        return {
            'name': name,
            'description': description,
            'body': parts[2].strip()
        }

    @classmethod
    def create_from_zip(cls, zip_file, project: Project, creator: User) -> 'Skill':
        """
        从上传的 zip 文件创建 Skill

        Args:
            zip_file: 上传的 zip 文件对象
            project: 所属项目
            creator: 创建者

        Returns:
            Skill 实例
        """
        import tempfile
        from django.conf import settings

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                with zipfile.ZipFile(zip_file, 'r') as zf:
                    cls._safe_extract_zip(zf, temp_dir)
            except zipfile.BadZipFile:
                raise ValidationError('无效的 zip 文件')

            skill_root = temp_dir
            items = os.listdir(temp_dir)
            if len(items) == 1 and os.path.isdir(os.path.join(temp_dir, items[0])):
                skill_root = os.path.join(temp_dir, items[0])

            skill_md_path = os.path.join(skill_root, 'SKILL.md')
            if not os.path.exists(skill_md_path):
                raise ValidationError('zip 文件中未找到 SKILL.md')

            with open(skill_md_path, 'r', encoding='utf-8') as f:
                skill_content = f.read()

            parsed = cls.parse_skill_md(skill_content)

            if cls.objects.filter(project=project, name=parsed['name']).exists():
                raise ValidationError(f"项目中已存在名为 '{parsed['name']}' 的 Skill")

            full_storage_path = None
            try:
                with transaction.atomic():
                    skill = cls.objects.create(
                        project=project,
                        creator=creator,
                        name=parsed['name'],
                        description=parsed['description'],
                        skill_content=skill_content,
                        is_active=True
                    )

                    skill_storage_path = f'skills/{project.id}/{skill.id}'
                    full_storage_path = os.path.join(settings.MEDIA_ROOT, skill_storage_path)
                    os.makedirs(full_storage_path, exist_ok=False)

                    for item in os.listdir(skill_root):
                        src = os.path.join(skill_root, item)
                        dst = os.path.join(full_storage_path, item)
                        if os.path.isdir(src):
                            shutil.copytree(src, dst)
                        else:
                            shutil.copy2(src, dst)

                    skill.skill_path = skill_storage_path
                    skill.save(update_fields=['skill_path'])

                return skill
            except Exception:
                if full_storage_path and os.path.isdir(full_storage_path):
                    shutil.rmtree(full_storage_path, ignore_errors=True)
                raise

    @classmethod
    def create_from_git(
        cls,
        git_url: str,
        project: Project,
        creator: User,
        branch: str = 'main'
    ) -> 'Skill':
        """
        从公开 Git 仓库导入 Skill

        Args:
            git_url: 仓库 URL（仅支持 https://github.com 或 https://gitlab.com）
            project: 所属项目
            creator: 创建者
            branch: 分支名（默认 main）

        Returns:
            Skill 实例
        """
        import tempfile
        import subprocess
        from urllib.parse import urlparse
        from django.conf import settings

        git_url = (git_url or '').strip()
        branch = (branch or 'main').strip() or 'main'

        parsed_url = urlparse(git_url)
        if parsed_url.scheme != 'https':
            raise ValidationError('仅支持 HTTPS 协议的仓库地址')
        if not parsed_url.netloc:
            raise ValidationError('无效的 Git 仓库地址')

        path_parts = [p for p in (parsed_url.path or '').split('/') if p]
        if len(path_parts) < 2:
            raise ValidationError('无效的 Git 仓库地址')

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_dir = os.path.join(temp_dir, 'repo')

            try:
                subprocess.run(
                    ['git', 'clone', '--depth', '1', '--branch', branch, git_url, repo_dir],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                raise ValidationError('Git 克隆超时（60秒）')
            except FileNotFoundError:
                raise ValidationError('服务器未安装 git，无法导入')
            except subprocess.CalledProcessError as e:
                stderr = (e.stderr or '').strip()
                raise ValidationError(f'Git 克隆失败: {stderr}' if stderr else 'Git 克隆失败')

            skill_md_path = None
            skill_root = repo_dir
            for root, dirs, files in os.walk(repo_dir):
                dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__')]
                if 'SKILL.md' in files:
                    skill_md_path = os.path.join(root, 'SKILL.md')
                    skill_root = root
                    break

            if not skill_md_path:
                raise ValidationError('仓库中未找到 SKILL.md')

            try:
                with open(skill_md_path, 'r', encoding='utf-8') as f:
                    skill_content = f.read()
            except UnicodeDecodeError:
                raise ValidationError('SKILL.md 文件编码必须为 UTF-8')

            parsed = cls.parse_skill_md(skill_content)

            if cls.objects.filter(project=project, name=parsed['name']).exists():
                raise ValidationError(f"项目中已存在名为 '{parsed['name']}' 的 Skill")

            full_storage_path = None
            try:
                with transaction.atomic():
                    skill = cls.objects.create(
                        project=project,
                        creator=creator,
                        name=parsed['name'],
                        description=parsed['description'],
                        skill_content=skill_content,
                        is_active=True
                    )

                    skill_storage_path = f'skills/{project.id}/{skill.id}'
                    full_storage_path = os.path.join(settings.MEDIA_ROOT, skill_storage_path)
                    os.makedirs(full_storage_path, exist_ok=False)

                    for item in os.listdir(skill_root):
                        if item == '.git':
                            continue
                        src = os.path.join(skill_root, item)
                        if os.path.islink(src):
                            continue
                        dst = os.path.join(full_storage_path, item)
                        if os.path.isdir(src):
                            shutil.copytree(src, dst, symlinks=False, ignore=shutil.ignore_patterns('.git'))
                        else:
                            shutil.copy2(src, dst)

                    skill.skill_path = skill_storage_path
                    skill.save(update_fields=['skill_path'])

                return skill
            except Exception:
                if full_storage_path and os.path.isdir(full_storage_path):
                    shutil.rmtree(full_storage_path, ignore_errors=True)
                raise

    def delete(self, *args, **kwargs):
        """删除 Skill 时同时删除文件"""
        full_path = self.get_full_path()
        if full_path:
            from django.conf import settings
            media_root = Path(settings.MEDIA_ROOT).resolve(strict=False)
            expected_root = (media_root / 'skills' / str(self.project_id) / str(self.id)).resolve(strict=False)
            target = Path(full_path).resolve(strict=False)
            if target == expected_root and target.exists():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                logger.warning("Refusing to delete unexpected Skill path: %s (expected %s)", target, expected_root)
        super().delete(*args, **kwargs)
