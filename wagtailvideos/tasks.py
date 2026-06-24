from celery import shared_task

from wagtailvideos import get_video_model
from wagtailvideos.signals import video_post_process


@shared_task
def video_post_process_task(video_id):
    Video = get_video_model()
    video = Video.objects.get(pk=video_id)
    video_post_process(video)
