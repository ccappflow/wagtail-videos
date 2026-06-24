from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from tests.utils import create_test_video_file
from wagtailvideos.models import Video


class FFmpegCompatShimTests(SimpleTestCase):
    def test_legacy_import_path_still_works(self):
        # `from wagtailvideos import ffmpeg` is kept as a compat shim for code
        # written against pre-7.x versions.
        from wagtailvideos import ffmpeg
        self.assertTrue(callable(ffmpeg.get_thumbnail))
        self.assertTrue(callable(ffmpeg.installed))
        self.assertTrue(callable(ffmpeg.get_stats))


class AsyncPostProcessTests(TestCase):
    @patch("wagtailvideos.signals.video_post_process")
    def test_processed_synchronously_by_default(self, mock_process):
        with self.captureOnCommitCallbacks(execute=True):
            Video.objects.create(title="v", file=create_test_video_file())
        # No async threshold configured -> heavy work runs inline.
        mock_process.assert_called()

    @override_settings(WAGTAILVIDEOS_ASYNC_POSTPROCESS_SIZE=1)
    @patch("wagtailvideos.signals.video_post_process")
    def test_deferred_to_task_above_threshold(self, mock_process):
        fake_tasks = MagicMock()
        with patch.dict("sys.modules", {"wagtailvideos.tasks": fake_tasks}):
            with self.captureOnCommitCallbacks(execute=True):
                video = Video.objects.create(
                    title="v", file=create_test_video_file())
            fake_tasks.video_post_process_task.delay.assert_called_once_with(
                video.pk)
        # Heavy work is deferred, not run inline.
        mock_process.assert_not_called()
