import os
import cv2
from bot.base.common import ImageMatchConfig

import weakref

TEMPLATE_INSTANCES = weakref.WeakSet()


class Template:
    template_name: str
    resource_path: str
    image_match_config: ImageMatchConfig

    def __init__(self,
                 template_name: str,
                 resource_path: str,
                 image_match_config: ImageMatchConfig = ImageMatchConfig()):
        self.resource_path = resource_path
        self.template_name = template_name
        self.template_path = os.path.join("resource" + self.resource_path, template_name.lower() + ".png")
        self.template_img = None
        self.image_match_config = image_match_config
        TEMPLATE_INSTANCES.add(self)

    @property
    def template_image(self):
        if self.template_img is None:
            try:
                self.template_img = cv2.imread(self.template_path, 0)
            except Exception:
                self.template_img = None
        return self.template_img


class UI:
    ui_name = None
    check_exist_template_list: list[Template] = None
    check_non_exist_template_list: list[Template] = None

    def __init__(self, ui_name, check_exist_template_list: list[Template],
                 check_non_exist_template_list: list[Template]):
        self.ui_name = ui_name
        self.check_exist_template_list = check_exist_template_list
        self.check_non_exist_template_list = check_non_exist_template_list


def purge_all_templates():
    try:
        for tpl in list(TEMPLATE_INSTANCES):
            try:
                tpl.template_img = None
            except Exception:
                pass
    except Exception:
        pass

NOT_FOUND_UI = UI("NOT_FOUND_UI", [], [])
