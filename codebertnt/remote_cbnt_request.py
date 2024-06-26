import logging
import shutil
import sys
from os import makedirs
from os.path import join, isdir, isfile
from pathlib import Path

from pandas import DataFrame

from cb import CodeBertMlmFillMask, predict_json_locs, PREDICTIONS_FILE_NAME, ListFileLocations, \
    predict_locs, MAX_BATCH_SIZE
from cb.job_config import DEFAULT_JOB_CONFIG
from codebertnt.locs_request import RemoteBusinessLocationsRequest
from codebertnt.rank_lines import order_lines_from_pickle, FL_COLUMN
from commons.pickle_utils import load_zipped_pickle, save_zipped_pickle

log = logging.getLogger(__name__)
log.addHandler(logging.StreamHandler(sys.stdout))


class RemotePredictBusinessLocations(RemoteBusinessLocationsRequest):

    def __init__(self, preds_output_dir,
                 *args, max_threads=4, job_config=DEFAULT_JOB_CONFIG, pickle_file_name=PREDICTIONS_FILE_NAME, **kwargs):
        super(RemotePredictBusinessLocations, self).__init__(*args, **kwargs)
        self.preds_output_dir = preds_output_dir
        self.pickle_file = join(preds_output_dir, pickle_file_name)
        self.max_threads = max_threads
        self.job_config = job_config
        self.file_locs = None

    def has_any_output(self):
        return isfile(self.pickle_file)

    def get_file_locs(self):
        if self.file_locs is None and self.has_any_output():
            self.file_locs = ListFileLocations.parse_raw(load_zipped_pickle(self.pickle_file))
        return self.file_locs

    def has_output(self):
        return self.has_any_output() and self.get_file_locs().job_done(self.job_config)

    def postprocess(self, locs_output_file):
        if not isfile(locs_output_file) and not self.has_any_output():
            log.error('files not found : \n{0} \n{1}'.format(locs_output_file, self.pickle_file))
        else:
            cbm = CodeBertMlmFillMask()
            if self.force_reload or not self.has_any_output():
                if not isdir(self.preds_output_dir):
                    try:
                        makedirs(self.preds_output_dir)
                    except FileExistsError:
                        log.debug("two threads created the directory concurrently.")
                results = predict_json_locs(locs_output_file, cbm, self.job_config, repo_dir=self.repo_path)
            else:
                results = predict_locs(self.get_file_locs(), cbm, self.job_config, batch_size=MAX_BATCH_SIZE, repo_dir=self.repo_path)
            json = results.json()
            save_zipped_pickle(json, self.pickle_file)
        if isdir(self.repo_path):
            shutil.rmtree(self.repo_path)

    def get_lines_ordered_by_min_conf(self, jdk_path: str) -> DataFrame:
        if self.force_reload or not self.has_any_output():
            self.call(jdk_path)
        if not self.has_any_output():
            raise Exception('failed')
        return order_lines_from_pickle((self.pickle_file, Path(self.repo_path).name),
                                       intermediate_dir=self.preds_output_dir + "_min_conf_order",
                                       preds_per_token=1,
                                       fl_column=FL_COLUMN, force_reload=False)



