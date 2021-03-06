import json
import numpy as np
import ray
import xgboost_ray as xgb
from airflow.decorators import dag, task
from airflow.utils.dates import days_ago
from airflow.operators.dummy_operator import DummyOperator

from datetime import datetime

from ray_provider.decorators.ray_decorators import ray_task
from ray_provider.xcom.ray_backend import RayBackend

from typing import Any


task_args = {"ray_conn_id": "ray_cluster_connection"}

# If you want to run against the entire HIGGS dataset, turn off local mode. Just a heads up, the dataset is quite
# large and will take a long time to load if you are not running ray in a cloud instance.
LOCAL_MODE = False

DataFrame = Any

@dag(
    default_args={
        "on_success_callback": RayBackend.on_success_callback,
        "on_failure_callback": RayBackend.on_failure_callback,
    },
    schedule_interval=None,
    start_date=datetime(2021, 3, 11),
    tags=["xgboost-modin-only"],
    catchup=False,
)
def xgboost_modin_breast_cancer():
    @ray_task(eager=True, **task_args)
    def load_dataframe() -> DataFrame:
        """Build a dataframe task."""
        print("Loading CSV.")
        if LOCAL_MODE:
            print("Loading simple")
            from sklearn import datasets

            data = datasets.load_breast_cancer(return_X_y=True)
        else:
            # import pandas as pd

            url = (
                "https://archive.ics.uci.edu/ml/machine-learning-databases/"
                "00280/HIGGS.csv.gz"
            )
            # colnames = ["label"] + ["feature-%02d" % i for i in range(1, 29)]
            # data = pd.read_csv(url, compression='gzip', names=colnames)

            import modin.pandas as mpd

            colnames = ["label"] + ["feature-%02d" % i for i in range(1, 29)]
            data = mpd.read_csv(url, names=colnames)

            print("loaded higgs")
        print("Loaded CSV.")
        return data

    @ray_task(**task_args)
    def create_data(data):
        print("RUNNING SOME CODE!")
        logfile = open("/tmp/ray/session_latest/custom.log", "w")

        def write(msg):
            logfile.write(f"{msg}\n")
            logfile.flush()

        write(f"Creating data matrix: {data, LOCAL_MODE}")
        if LOCAL_MODE:
            from sklearn.model_selection import train_test_split

            write("Splitting data")
            data, labels = data
            train_x, test_x, train_y, test_y = train_test_split(
                data, labels, test_size=0.25
            )

            train_set = xgb.RayDMatrix(train_x, train_y)
            test_set = xgb.RayDMatrix(test_x, test_y)
        else:
            df_train = data[(data["feature-01"] < 0.4)]
            colnames = ["label"] + ["feature-%02d" % i for i in range(1, 29)]
            train_set = xgb.RayDMatrix(df_train, label="label", columns=colnames)
            df_validation = data[
                (data["feature-01"] >= 0.4) & (data["feature-01"] < 0.8)
            ]
            test_set = xgb.RayDMatrix(df_validation, label="label")
        write("finished data matrix")
        return train_set, test_set

    @ray_task(**task_args)
    def train_model(data) -> None:
        logfile = open("/tmp/ray/session_latest/custom.log", "w")

        def write(msg):
            logfile.write(f"{msg}\n")
            logfile.flush()

        dtrain, dvalidation = data
        evallist = [(dvalidation, "eval")]
        evals_result = {}
        config = {
            "tree_method": "hist",
            "eval_metric": ["logloss", "error"],
        }
        write("Start training")
        bst = xgb.train(
            params=config,
            dtrain=dtrain,
            evals_result=evals_result,
            ray_params=xgb.RayParams(
                max_actor_restarts=1, num_actors=2, cpus_per_actor=2
            ),
            num_boost_round=100,
            evals=evallist,
        )
        write("finish training")
        return bst

    build_raw_df = load_dataframe()
    data = create_data(build_raw_df)
    trained_model = train_model(data)

    kickoff_dag = DummyOperator(task_id="kickoff_dag")
    complete_dag = DummyOperator(task_id="complete_dag")

    kickoff_dag >> build_raw_df
    trained_model >> complete_dag


xgboost_modin_breast_cancer = xgboost_modin_breast_cancer()
