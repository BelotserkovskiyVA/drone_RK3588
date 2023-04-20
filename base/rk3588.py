import json
from multiprocessing import Process, Queue
from pathlib import Path

from rknnlite.api import RKNNLite

from base.camera import Cam
from base.inference import Yolov5, UNet, ResNet
from addons.odometry import mapping


CONFIG_FILE = str(Path(__file__).parent.parent.absolute()) + "/config.json"
with open(CONFIG_FILE, 'r') as config_file:
    cfg = json.load(config_file)


class RK3588():
    """Class for object detection on RK3588/RK3588S
    
    Attributes
    ---------------------------------------------------------------------------
    Queues
    -----------------------------------
    _q_pre : multiprocessing.Queue
        Queue for sending raw frames, resized frames and frames ids from
        camera reading process to inference process
    _q_outs : multiprocessing.Queue
        Queue for sending inference results, raw frames and frames ids from
        inference process to post_process process
    _q_post : multiprocessing.Queue
        Queue for sending raw frames, frames with bboxes, numpy array with
        detections and frames ids from post_process process to ouput
    -----------------------------------
    Camera
    -----------------------------------
    cam : camera.Cam
        Camera object for creating recording, showing process
    -----------------------------------
    Inference
    -----------------------------------
    model : inference.Model or inference.VariableModel
        Model object for creating inference processes
    -----------------------------------
    Processes
    -----------------------------------
    _rec : multiprocessing.Process
        Process for recording frames
    _pre_inf : multiprocessing.Process
        Process for inferencing frames (recomended amount is 3 and should equal
        post_process processes)
    _post : multiprocessing.Process
        Process for post processing frames (recomended amount is 3 and should
        equal inference processes)
    -----------------------------------
    ---------------------------------------------------------------------------
    
    Methods
    ---------------------------------------------------------------------------
    start() : None
        Starts all processes (recording process, inference process(es),
        post_process process(es))
    show() : None
        Create cv2 window with inferenced frames (frames with bboxes on them)
    get_data() : tuple(np.ndarray, np.ndarray, np.ndarray, int) | None
        Returns raw frames, frames with bboxes, numpy array with detections
        and frames ids
    ---------------------------------------------------------------------------
    """
    def __init__(self):
        self._q_pre = Queue(maxsize=cfg["inference"]["buf_size"])
        self._q_outs = Queue(maxsize=cfg["inference"]["buf_size"])
        self._q_post = Queue(maxsize=cfg["inference"]["buf_size"])
        self._cam = Cam(source = cfg["camera"]["source"],
                        q_in = self._q_post,
                        q_out = self._q_pre
                )
        self._cores=[RKNNLite.NPU_CORE_0,
                     RKNNLite.NPU_CORE_1,
                     RKNNLite.NPU_CORE_2
                    ]
        self.model = [ResNet(proc=i,
                             core=self._cores[i%3]
                             )
                             for i in range(cfg["inference"]["inf_proc"])
                    ]
        self._rec = Process(target=self._cam.record, #Camera()._pre_process(frame) <- rgb2bgr
                            daemon=True
                            )
        self._pre_inf = [Process(target=self.model[i].inference, # pre_process + inf
                                 kwargs={'q_in' : self._q_pre,
                                         'q_out' : self._q_outs,
                                        },
                                 daemon=True
                                )
                                for i in range(len(self.model))
                        ]
        self._post = [Process(target=self.model[i].post_process,
                              kwargs={"q_in" : self._q_outs,
                                      "q_out" : self._q_post
                                      },
                              daemon=True
                              )
                              for i in range(cfg["inference"]["post_proc"])
                    ]
        self._map = Process(target=mapping,
                            kwargs={"q_in" : self._q_post},
                            daemon=True
                            )
        
    def start(self):
        self._rec.start()
        for inference in self._pre_inf: inference.start()
        for post_process in self._post: post_process.start()
        self._map.start()

    def show(self, start_time):
        self._cam.show(start_time)

    def get_data(self):
        if self._q_post.empty():
            return None
        return self._q_post.get()
