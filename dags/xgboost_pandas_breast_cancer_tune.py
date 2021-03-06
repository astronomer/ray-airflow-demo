import os
import json
import numpy as np
import ray
import xgboost_ray as xgbr
import xgboost as xgb
from airflow.decorators import dag, task
from airflow.utils.dates import days_ago
from airflow.operators.dummy_operator import DummyOperator

from datetime import datetime

from ray_provider.decorators.ray_decorators import ray_task

from ray import tune
from ray.tune.schedulers import ASHAScheduler
from ray_provider.xcom.ray_backend import RayBackend

from xgboost_ray.tune import TuneReportCheckpointCallback


task_args = {"ray_conn_id": "ray_cluster_connection"}

SIMPLE = True
RAY_PARAMS = xgbr.RayParams(max_actor_restarts=1, num_actors=1, cpus_per_actor=1)
ROOT_DIR = "."
LOCAL_DIR = f"{ROOT_DIR}/ray_results"


@dag(
    default_args={
        "on_success_callback": RayBackend.on_success_callback,
        "on_failure_callback": RayBackend.on_failure_callback,
    },
    schedule_interval=None,
    start_date=datetime(2021, 3, 11),
    tags=["xgboost-pandas-only"],
    catchup=False,
)
def xgboost_pandas_breast_cancer_tune():
    @ray_task(**task_args)
    def load_dataframe() -> "ray.ObjectRef":
        """
        build dataframe from breast cancer dataset
        """
        print("Loading CSV")

        if SIMPLE:
            print("Loading simple from sklearn.datasets")
            from sklearn import datasets

            data = datasets.load_breast_cancer(return_X_y=True)
        else:
            import pandas as pd

            # import modin.pandas as mpd -- currently does not work.
            url = (
                "https://archive.ics.uci.edu/ml/machine-learning-databases/"
                "00280/HIGGS.csv.gz"
            )
            colnames = ["label"] + ["feature-%02d" % i for i in range(1, 29)]
            data = pd.read_csv(url, compression="gzip", names=colnames)
            # data = pd.read_csv("/home/astro/HIGGS.csv.gz", names=colnames)
            print("loaded higgs")
        print("Loaded CSV.")

        return data

    @ray_task(**task_args)
    def split_train_test(data):
        print("Splitting Data to Train and Test Sets")

        logfile = open("/tmp/ray/session_latest/custom.log", "w")

        def write(msg):
            logfile.write(f"{msg}\n")
            logfile.flush()

        print(f"Creating data matrix: {data, SIMPLE}")

        if SIMPLE:
            from sklearn.model_selection import train_test_split

            print("Splitting data")
            data, labels = data
            train_x, test_x, train_y, test_y = train_test_split(
                data, labels, test_size=0.25
            )

            train_set = xgbr.RayDMatrix(train_x, train_y)
            test_set = xgbr.RayDMatrix(test_x, test_y)
        else:
            df_train = data[(data["feature-01"] < 0.4)]
            colnames = ["label"] + ["feature-%02d" % i for i in range(1, 29)]
            train_set = xgbr.RayDMatrix(df_train, label="label", columns=colnames)
            df_validation = data[
                (data["feature-01"] >= 0.4) & (data["feature-01"] < 0.8)
            ]
            test_set = xgbr.RayDMatrix(df_validation, label="label")

        print("finished data matrix")

        return train_set, test_set

    # This could be in a library of trainables
    def train_model(config, checkpoint_dir=None, data_dir=None, data=()):
        logfile = open("/tmp/ray/session_latest/custom.log", "w")

        def write(msg):
            logfile.write(f"{msg}\n")
            logfile.flush()

        dtrain, dvalidation = data
        evallist = [(dvalidation, "eval")]
        # evals_result = {}
        config = {
            "tree_method": "hist",
            "eval_metric": ["logloss", "error"],
        }
        print("Start training")
        bst = xgbr.train(
            params=config,
            dtrain=dtrain,
            ray_params=RAY_PARAMS,
            num_boost_round=100,
            evals=evallist,
            callbacks=[TuneReportCheckpointCallback(filename=f"model.xgb")],
        )

    @ray_task(**task_args)
    def tune_model(data):
        logfile = open("/tmp/ray/session_latest/custom.log", "w")

        def write(msg):
            logfile.write(f"{msg}\n")
            logfile.flush()

        search_space = {
            # You can mix constants with search space objects.
            "objective": "binary:logistic",
            "eval_metric": ["logloss", "error"],
            "max_depth": tune.randint(1, 9),
            "min_child_weight": tune.choice([1, 2, 3]),
            "subsample": tune.uniform(0.5, 1.0),
            "eta": tune.loguniform(1e-4, 1e-1),
        }

        print("enabling aggressive early stopping of bad trials")
        # This will enable aggressive early stopping of bad trials.
        scheduler = ASHAScheduler(
            max_t=4, grace_period=1, reduction_factor=2  # 10 training iterations
        )

        print("Tuning")

        analysis = tune.run(
            tune.with_parameters(
                train_model,
                data=data
                # checkpoint_dir=f"{LOCAL_DIR}/checkpoints",
                # data_dir=f"{LOCAL_DIR}/data",
            ),
            metric="eval-logloss",
            mode="min",
            local_dir=LOCAL_DIR,
            # You can add "gpu": 0.1 to allocate GPUs
            resources_per_trial=RAY_PARAMS.get_tune_resources(),
            config=search_space,
            num_samples=4,
            scheduler=scheduler,
        )

        print("Done Tuning")

        return analysis

    @ray_task(**task_args)
    def load_best_model_checkpoint(analysis):
        print("Running")
        logfile = open("/tmp/ray/session_latest/custom.log", "w")

        def write(msg):
            logfile.write(f"{msg}\n")
            logfile.flush()

        print("Checking Analysis")
        print(f"Checkpoint is at: {analysis.best_checkpoint}")

        best_bst = xgb.Booster()

        print(
            f"Analysis Best Result on eval-error is: {analysis.best_result['eval-error']}"
        )
        print("Loading Model with Best Params")

        best_bst.load_model(os.path.join(analysis.best_checkpoint, "model.xgb"))
        accuracy = 1.0 - analysis.best_result["eval-error"]

        print(f"Best model parameters: {analysis.best_config}")
        print(f"Best model total accuracy: {accuracy:.4f}")

        # We could now do further predictions with
        # best_bst.predict(...)
        return best_bst

    build_raw_df = load_dataframe()
    data = split_train_test(build_raw_df)
    analysis = tune_model(data)
    best_checkpoint = load_best_model_checkpoint(analysis)
    kickoff_dag = DummyOperator(task_id="kickoff_dag")
    complete_dag = DummyOperator(task_id="complete_dag")

    kickoff_dag >> build_raw_df
    best_checkpoint >> complete_dag


xgboost_pandas_breast_cancer_tune = xgboost_pandas_breast_cancer_tune()
