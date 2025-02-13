"""
Utils functions for Syn
"""


import os
import sys


import numpy as np
import pandas as pd

from sklearn.metrics import log_loss
from catboost import CatBoostClassifier, CatBoostRegressor, Pool

import os
import shutil
from typing import Optional, List, Dict, Tuple
import json


from sklearn.metrics import classification_report
from sklearn import metrics



def concat_data(
    data_path: str,
    split: str = "train",
    num_features_list: list = None,
    cat_features_list: list = None,
    y_feature: str = "y",
    is_y_cat: bool = False,
    **kwargs,
) -> pd.DataFrame:
    """
    Aggregate generated features and the response to a dataframe.
    - data_path: path to generated data folder with same naming convention as in the tddpm repo, sampling part. e.g., under this path, we might have:
        - y_{split}.npy
        - X_num_{split}.npy
        - X_cat_{split}.npy
    - num_features_list: list of numerical features names.
    - cat_features_list: list of categorical features names.
    - y_feature: name of the response
    - is_y_cat: whether the response is categorical or not. Will be used to determine the type of the response column.

    Returns a dataframe with columns: [y_feature] + num_features_list + cat_features_list, in original scale
    """
    assert split in ["train", "val", "test"], "split should be one of train/val/test"
    concat_list, col_names = [], []

    # response
    y_test_syn = np.load(os.path.join(data_path, f"y_{split}.npy"))

    concat_list.append(y_test_syn[:, None])
    col_names += [y_feature]

    X_num_path = os.path.join(data_path, f"X_num_{split}.npy")
    if os.path.exists(X_num_path):
        X_num_test_syn = np.load(X_num_path)

        concat_list.append(X_num_test_syn)
        if num_features_list is not None:
            assert len(num_features_list) == X_num_test_syn.shape[1]
        else:
            num_features_list = [f"num_{i}" for i in range(X_num_test_syn.shape[1])]
        col_names += num_features_list

    X_cat_path = os.path.join(data_path, f"X_cat_{split}.npy")
    if os.path.exists(X_cat_path):
        X_cat_test_syn = np.load(X_cat_path, allow_pickle=True)

        concat_list.append(X_cat_test_syn)
        if cat_features_list is not None:
            assert len(cat_features_list) == X_cat_test_syn.shape[1]
        else:
            cat_features_list = [f"cat_{i}" for i in range(X_cat_test_syn.shape[1])]
        col_names += cat_features_list
    else:
        # for cat_list created later
        cat_features_list = []

    temp_df = pd.DataFrame(
        np.concatenate(concat_list, axis=1),
        columns=col_names,
    )

    cat_list = (
        cat_features_list if is_y_cat == False else cat_features_list + [y_feature]
    )

    new_types = {
        col_name: "category" if col_name in cat_list else "float"
        for col_name in col_names
    }

    temp_df = temp_df.astype(new_types)

    return temp_df


def catboost_prepare_pool(
    temp_df: pd.DataFrame,
    num_features_list: Optional[list] = None,
    cat_features_list: Optional[list] = None,
    y_feature: str = "y",
    null_features_list=[],
):
    """Prepare catboost pool for either training or testing."""
    cat_features_list = [] if cat_features_list is None else cat_features_list
    num_features_list = [] if num_features_list is None else num_features_list

    cat_features_filtered = [
        f for f in cat_features_list if f not in null_features_list
    ]
    temp_data = Pool(
        data=temp_df[num_features_list + cat_features_list].drop(
            columns=null_features_list
        ),
        label=temp_df[y_feature],
        cat_features=cat_features_filtered,
    )
    return temp_data


def catboost_pred_model(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    num_features_list: Optional[list] = None,
    cat_features_list: Optional[list] = None,
    y_feature: str = "y",
    is_y_cat: bool = False,
    null_features_list: list = [],
    **kwargs,
):
    """
    Get a full predictive model of y_feature from train_df and test_df using catboost.
    - train_df, test_df: training and testing data in pandas dataframes, with columns: [y_feature] + num_features_list + cat_features_list
    - cat_features_list: list of categorical features names.
    - y_feature: name of the response
    - is_y_cat: whether the response is categorical or not. Will be used to determine the type of prediction
    - null_features_list: list of features names that will be removed during training

    It is suggested that one pass `iterations` and `loss_function` as additional kwargs for CatBoosting training.

    Also note that this function currently only supports single response with either numerical value or binary categorical value.
    """

    if len(null_features_list) == 0:
        print(f"no null features, using all specified features for training")
    else:
        print(f"null features {null_features_list} will be removed during training")

    train_data = catboost_prepare_pool(
        train_df,
        num_features_list,
        cat_features_list,
        y_feature,
        null_features_list,
    )
    test_data = catboost_prepare_pool(
        test_df,
        num_features_list,
        cat_features_list,
        y_feature,
        null_features_list,
    )


    if is_y_cat:
        model = CatBoostClassifier(**kwargs, allow_writing_files=False)
    else:
        model = CatBoostRegressor(**kwargs, allow_writing_files=False)

    model.fit(train_data, eval_set=test_data)

    return model


def test_rmse(
    catmodel: CatBoostRegressor,
    test_df: pd.DataFrame,
    num_features_list: Optional[list] = None,
    return_individual: bool = False,
):
    """RMSE evalauted on test dataset using a trained CatBoost regressor."""
    if num_features_list is None:
        num_features_list = [f"num_{i}" for i in range(test_df.shape[1] - 1)]
    temp_df = test_df.copy()
    test_df_pool = catboost_prepare_pool(temp_df, num_features_list=num_features_list)
    preds = catmodel.predict(test_df_pool)
    true_y = temp_df["y"]
    rmse = np.sqrt(np.mean((preds - true_y) ** 2))

    if not return_individual:
        return rmse
    else:
        if not isinstance(true_y, np.ndarray):
            true_y = true_y.to_numpy()
        if not isinstance(preds, np.ndarray):
            preds = preds.to_numpy()
        return true_y, preds, rmse


def test_acc(
    catmodel: CatBoostClassifier,
    test_df: pd.DataFrame,
    **kwargs,
):
    """Accuracy evalauted on test dataset using a trained CatBoost classifier."""

    temp_df = test_df.copy()
    test_df_pool = catboost_prepare_pool(
        temp_df,
        num_features_list=kwargs["num_features_list"],
        cat_features_list=kwargs["cat_features_list"],
        y_feature=kwargs["y_feature"],
    )

    preds = catmodel.predict(test_df_pool)
    preds = np.array(preds, dtype=int)

    true_y = temp_df[kwargs["y_feature"]].to_numpy()
    true_y = np.array(true_y, dtype=int)

    acc = np.mean(preds == true_y)
    return acc


def test_scores_catboost(
    catmodel: CatBoostClassifier,
    test_df: pd.DataFrame,
    **kwargs,
):
    """
    Evaluation metrics on test dataset using a trained CatBoost classifier. Provided metrics include:
    - accuracy
    - F1 score
    - AUROC
    - AUPRC
    """

    temp_df = test_df.copy()
    test_df_pool = catboost_prepare_pool(
        temp_df,
        num_features_list=kwargs["num_features_list"],
        cat_features_list=kwargs["cat_features_list"],
        y_feature=kwargs["y_feature"],
    )

    probs = catmodel.predict(test_df_pool, prediction_type="Probability")
    preds = catmodel.predict(test_df_pool)
    preds = np.array(preds, dtype=int)

    true_y = temp_df[kwargs["y_feature"]].to_numpy()
    true_y = np.array(true_y, dtype=int)

    # overall accuracy
    acc = np.mean(preds == true_y)
    
    # macro F1 score
    temp = classification_report(true_y, preds, digits=3, output_dict=True)
    f1_macro = temp["macro avg"]["f1-score"]
    
    # auroc
    fpr, tpr, thresholds = metrics.roc_curve(true_y, probs[:, 1], pos_label=1)
    auroc = metrics.auc(fpr, tpr)
    
    # auprc
    pr, re, thresholds = metrics.precision_recall_curve(true_y, probs[:, 1], pos_label=1)
    auprc = metrics.auc(re, pr)

    return {
        "accuracy": acc,
        "f1_macro": f1_macro,
        "auroc": auroc,
        "auprc": auprc,
    }

def load_pred_models(
    dataset_name: str,
    null_features_list: List[str],
    is_y_cat: bool = False,
    root_dir: str = ".",
    **kwargs,
) -> dict:
    """
    Load full and partial predictive models for the response

    Returns a dictionary of the full and partial models: {"full": full_model, "partial": partial_model}
    """
    suffix = "_".join(null_features_list)

    pred_model_dict = {}
    pred_ckpt_folder = os.path.join(root_dir, dataset_name, f"pred_model_ckpt")

    full_ckpt_path = os.path.join(pred_ckpt_folder, f"model_full_{suffix}.ckpt")
    full_model = CatBoostRegressor() if not is_y_cat else CatBoostClassifier()
    full_model.load_model(full_ckpt_path)
    pred_model_dict["full"] = full_model

    partial_ckpt_path = os.path.join(pred_ckpt_folder, f"model_partial_{suffix}.ckpt")
    partial_model = CatBoostRegressor() if not is_y_cat else CatBoostClassifier()
    partial_model.load_model(partial_ckpt_path)
    pred_model_dict["partial"] = partial_model

    return pred_model_dict


def catboost_null_models(
    train_df,
    eval_df,
    num_features_list,
    cat_features_list,
    null_feature_names,
    ckpt_dir,
    **kwargs,
) -> dict:
    """
    Get predictive models for null features (must be NUMERICAL) using all the other features
    - train_df, eval_df: train and eval dataframes with columns [y_feature] + num_features_list + cat_features_list in original scale
    - num_features_list, cat_features_list: list of numerical and categorical features
    - null_feature_names: names of the null feature to be predicted, MUST be in num_features_list
    - ckpt_dir: directory to save the models

    Returns a dictionary of ckpt paths: {null_feature_name: ckpt_path}
    """
    assert set(null_feature_names).issubset(
        set(num_features_list)
    ), "null features must be a subset of numerical features"

    leftover_num_features = [
        f for f in num_features_list if f not in null_feature_names
    ]  # all but the null features

    model_ckpt_path_dict = {}
    for null_feature in null_feature_names:
        ckpt_null_feature_path = os.path.join(ckpt_dir, f"{null_feature}.ckpt")
        model_ckpt_path_dict[null_feature] = ckpt_null_feature_path

        temp_model = catboost_pred_model(
            train_df=train_df,
            test_df=eval_df,
            num_features_list=leftover_num_features,
            cat_features_list=cat_features_list,
            is_y_cat=False,
            y_feature=null_feature,
        )
        temp_model.save_model(ckpt_null_feature_path)

    return model_ckpt_path_dict


def load_twin_null_models(dataset_name: str, null_features_list: List[str], root_dir: str = ".") -> dict:
    """
    Load null model checkpoints for twin 1 and twin 2. This function will load ckpt in:

    syninf/{dataset_name}/null_model_ckpt/twin_{1/2}_{null_features_suffix}/
    - {null_feature_name_1}.ckpt
    - ...

    Returns a dictionary of null models: {twin_1/twin_2: {null_feature_name: null_model}}

    Example:
    >>> dataset_name = "california"
    >>> null_features_list = ["MedInc"]
    >>> twin_null_model_dict = load_twin_null_models(dataset_name, null_features_list)
    """
    suffix = "_".join(null_features_list)

    twin_null_model_dict = {"twin_1": {}, "twin_2": {}}
    for null_feature in null_features_list:
        null_model_ckpt_path_twin_1 = os.path.join(
            root_dir,
            f"{dataset_name}/null_model_ckpt/twin_1_{suffix}/{null_feature}.ckpt",
        )
        temp_model = CatBoostRegressor()
        temp_model.load_model(null_model_ckpt_path_twin_1)
        twin_null_model_dict["twin_1"][null_feature] = temp_model

        null_model_ckpt_path_twin_2 = os.path.join(
            root_dir,
            f"{dataset_name}/null_model_ckpt/twin_2_{suffix}/{null_feature}.ckpt",
        )
        temp_model = CatBoostRegressor()
        temp_model.load_model(null_model_ckpt_path_twin_2)
        twin_null_model_dict["twin_2"][null_feature] = temp_model

    return twin_null_model_dict


def blackbox_test_stat(
    infer_df: pd.DataFrame,
    full_model: CatBoostClassifier,
    partial_model: CatBoostClassifier,
    num_features_list: Optional[list] = None,
    cat_features_list: Optional[list] = None,
    y_feature: str = "y",
    is_y_cat: bool = False,
    null_feature_names: list = [],
    loss_function: str = "MAE",
    **kwargs,
):
    """
    Compute the test statistic of the blackbox test.
    - infer_df: inference dataframe with columns: [y_feature] + num_features_list + cat_features_list
    - full_model, partial_model: predictive models of y_feature, with all features and all features but null features, respectively.
    - cat_features_list: list of categorical features names.
    - y_feature: name of the response
    - is_y_cat: whether the response is categorical or not. Will be used to determine the type of prediction
    - null_feature_names: list of null feature names
    - loss_function: loss function for regression to get the residuals

    Returns the blackbox test statistics on inference sample, log loss is used for binary response and MAE is used for numerical response.
    """
    infer_pool_full = catboost_prepare_pool(
        infer_df, num_features_list, cat_features_list, y_feature
    )
    infer_pool_partial = catboost_prepare_pool(
        infer_df, num_features_list, cat_features_list, y_feature, null_feature_names
    )

    if is_y_cat:
        pred_prob_full = full_model.predict(
            infer_pool_full, prediction_type="Probability"
        )
        residuals_full = np.array(
            [
                -np.log(pred_prob_full[i, int(label)])
                for i, label in enumerate(infer_pool_full.get_label())
            ]
        )

        pred_prob_partial = partial_model.predict(
            infer_pool_partial, prediction_type="Probability"
        )
        residuals_partial = np.array(
            [
                -np.log(pred_prob_partial[i, int(label)])
                for i, label in enumerate(infer_pool_partial.get_label())
            ]
        )

    else:
        pred_full = full_model.predict(infer_pool_full)
        residuals_full = np.abs(pred_full - infer_pool_full.get_label())

        pred_partial = partial_model.predict(infer_pool_partial)
        residuals_partial = np.abs(pred_partial - infer_pool_partial.get_label())

        if loss_function == "RMSE":
            residuals_full = residuals_full**2
            residuals_partial = residuals_partial**2

    residuals_diff = residuals_partial - residuals_full
    test_stat = (
        np.mean(residuals_diff)
        / np.std(residuals_diff)
        * np.sqrt(residuals_diff.shape[0])
    )
    return test_stat


# replace null features with their predictions: numerical onlyu
def replace_null_features(
    target_df: pd.DataFrame,
    twin_null_model_dict: dict,
    twin_folder: str,
) -> pd.DataFrame:
    """
    Replace null features of target_df with their predictions from null models
    - target_df: a dataframe with null features
    - twin_null_model_dict: a dictionary of null models: {twin_1/twin_2: {null_feature_name: null_model}}
    - twin_folder: either twin_1 or twin_2

    Returns a dataframe with null features replaced by their predictions
    """
    assert twin_folder in [
        "twin_1",
        "twin_2",
    ], "twin_folder must be either twin_1 or twin_2"

    temp_df = target_df.copy()

    null_model_dict = twin_null_model_dict[twin_folder]
    for null_feature_name, null_model in null_model_dict.items():
        temp_df[null_feature_name] = null_model.predict(
            target_df[null_model.feature_names_]
        )

    return temp_df


def save_split_by_type(
    split_df: pd.DataFrame,
    split: str = "train",
    df_type: str = "num",
    train_data_dir: str = "train_data",
    is_y_cat: bool = False,
):
    """
    Save a split of the data as numpy array, by type (num, cat, y).
    - The split_df must be pure, i.e. only contain the features of the type specified by df_type.
    - split_df: the split of the data to be saved
    - split: one of train, val, test
    - df_type: one of num, cat, y
    - train_data_dir: the directory to save the data
    - is_y_cat: whether the target is categorical

    dtype of each converted numpy array: float32 for num and y (is_y_cat=False), int64 for y (is_y_cat=True), <U26 for cat (string)
    """

    if len(split_df) == 0:
        # empty dataframe, save nothing
        print(f"empty dataframe, nothing saved")
        return

    assert split in ["train", "val", "test"], "split must be one of train, val, test"
    assert df_type in ["num", "cat", "y"], "df_type must be one of num, cat, y"

    np_array_name = []
    np_array_name.append("y" if df_type == "y" else "X")
    if df_type != "y":
        np_array_name.append(df_type)
    np_array_name.append(split)
    np_array_name = "_".join(np_array_name) + ".npy"

    np_array_dtype = "<U26" if df_type == "cat" else np.float32
    if df_type == "y" and is_y_cat:
        np_array_dtype = "int64"

    np_array = split_df.to_numpy(dtype=np_array_dtype)

    np_save_path = os.path.join(train_data_dir, np_array_name)
    np.save(np_save_path, np_array)
    print(f"saved {np_save_path}")

    return train_data_dir


def prepare_train_data(
    temp_df: pd.DataFrame,
    train_data_dir: str = "train_data",
    split: Tuple[float] = (0.7, 0.2, 0.1),
    seed=2023,
    num_features_list: list = None,
    cat_features_list: list = None,
    y_feature: str = "y",
    is_y_cat: bool = False,
    reverse: bool = False,
):
    """
    Prepare training folder for tabddpm. The folder contains:
    - info.json: a dictionary containing the meta information of the dataset
    - X/y_num/cat_train/val/test.npy: numpy array of the corresponding data split

    Arguments:
    - temp_df: the overall dataframe
    - train_data_dir: temporary directory to save the training data
    - split: the split ratio of train, val, test
    - reverse: whether to reverse the train and test split (ONLY use it when creating twin folders)

    Returns train_data_dir from where train_tabddpm can be called directly

    Example:
    >>> # prepare data for tabddpm training
    >>> temp_df = ...
    >>> names_dict = ...
    >>> split = (0.98, 0.01, 0.01)
    >>> seed = 2023
    >>> train_data_dir = prepare_train_data(
    >>>     temp_df=temp_df,
    >>>     split=split,
    >>>     seed=seed,
    >>>     **names_dict
    >>> )
    >>> # tabddpm training
    >>> pipeline_config_path = ...
    >>> train_tabddpm(
    >>>     pipeline_config_path=pipeline_config_path,
    >>>     real_data_dir=train_data_dir,
    >>>     steps=1000,
    >>>     device="cuda:0"
    >>> )

    """
    # Create parent dir to save the result, remove if already exists
    if os.path.exists(train_data_dir):
        shutil.rmtree(train_data_dir)
    os.makedirs(train_data_dir)

    # # Create parent dir to save the result, overwirte if already exists
    # if not os.path.exists(train_data_dir):
    #     os.makedirs(train_data_dir)

    train_size, val_size, test_size = (
        int(split[0] * len(temp_df)),
        int(split[1] * len(temp_df)),
        int(split[2] * len(temp_df)),
    )
    train_df, val_df, test_df = np.split(
        temp_df.sample(frac=1, random_state=seed), [train_size, train_size + val_size]
    )

    if reverse:
        train_size, test_size = test_size, train_size
        train_df, test_df = test_df, train_df

    # save the info dictionary
    info_dict = {
        "name": "Dataset name",
        "id": "Dataset id",
        "task_type": "binclass" if is_y_cat else "regression",
        "n_num_features": len(num_features_list),
        "n_cat_features": len(cat_features_list),
        "test_size": test_size,
        "train_size": train_size,
        "val_size": val_size,
    }
    json.dump(info_dict, open(os.path.join(train_data_dir, "info.json"), "w"))

    # save the train, val, test data as numpy array, by type (num, cat, y)

    df_type_map = {
        "y": y_feature,
        "num": num_features_list,
        "cat": cat_features_list,
    }

    for split in ["train", "val", "test"]:
        for df_type in ["num", "cat", "y"]:
            _ = save_split_by_type(
                split_df=eval(f"{split}_df")[df_type_map[df_type]],
                split=split,
                df_type=df_type,
                train_data_dir=train_data_dir,
                is_y_cat=is_y_cat,
            )

    return train_data_dir


def combine_Hommel(p_value_list: List[float]) -> float:
    """
    Combine p-values using Hommel's method.
    - p_value_list: list of p-values
    - https://browse.arxiv.org/pdf/2103.04985.pdf: equation (7)
    """
    p_value_sorted = np.array(sorted(p_value_list))
    U = len(p_value_list)
    C = np.sum(1 / np.arange(1, U + 1))

    return np.minimum(C * np.min(p_value_sorted * U / np.arange(1, U + 1)), 1)


def bias_correction(
    test_stat_null_dist: List[float], test_stat_type1: List[float], direction="greater"
):
    """
    Correct bias of the null distribution, and the type 1 error distribution based on direction (greater, less, equal)

    Direction means we are doing one-sided test, and the test statistics for type-I error tuning/control is adjusted towards that direction.
    """
    assert direction in [
        "greater",
        "less",
        "equal",
    ], "direction must be greater, less or equal"
    null_dist, type1 = np.array(test_stat_null_dist), np.array(test_stat_type1)
    bias_null, bias_type1 = null_dist.mean(), type1.mean()
    null_dist_corrected, type1_corrected = (
        null_dist - bias_type1,
        type1 + bias_null - 2 * bias_type1,
    )

    diff = bias_null - bias_type1
    if direction == "greater":
        type1_corrected = type1_corrected + np.abs(diff)
    elif direction == "less":
        type1_corrected = type1_corrected - np.abs(diff)
    else:
        type1_corrected = type1 - bias_type1

    return null_dist_corrected, type1_corrected





def get_p_values(null_ecdf, t_null_ecdf, direction = "greater"):
    """
    Get P-values based on one reference null distribution and a distribution of the test statistic under H0
    - null_ecdf: empirical CDF of the reference null distribution, used to get p-values
    - t_null_ecdf: empirical CDF of the test statistic under H0
    """
    if direction == "greater":
        p_values = [np.mean(null_ecdf >= t) for t in t_null_ecdf]
    elif direction == "less":
        p_values = [np.mean(null_ecdf <= t) for t in t_null_ecdf]
    elif direction == "two-sided":
        p_values = [2 * min(np.mean(null_ecdf >= t), np.mean(null_ecdf <= t)) for t in t_null_ecdf]
    
    return p_values


def soft_type_i(p_values, alpha = 0.05, epsilon = 0.01):
    """
    Type-I error rate with soft thresholding based on p-values
    - p_values: p-values obtained under the null hypothesis
    """
    type_i_error = np.mean(np.array(p_values) <= alpha - epsilon)
    return type_i_error


def soft_type_i_errors(result_dict, direction = "greater", alpha = 0.05, epsilon = 0.01):
    """
    Type-I errors w.r.t. synthetic-to-raw ratio based on result_dict.
    """
    rho_list, type_i_error_list = [], []
    for rho_str in result_dict.keys():
        p_values_twin_1 = get_p_values(
            np.array(result_dict[rho_str]["twin_1"]["test_stat_null"]),
            np.array(result_dict[rho_str]["twin_2"]["test_stat_null"]),
            direction = direction,
        )
        p_values_twin_2 = get_p_values(
            np.array(result_dict[rho_str]["twin_2"]["test_stat_null"]),
            np.array(result_dict[rho_str]["twin_1"]["test_stat_null"]),
            direction = direction
        )
        p_values_combined = [combine_Hommel([p1, p2]) for p1, p2 in zip(p_values_twin_1, p_values_twin_2)]
        
        rho_list.append(float(rho_str))
        type_i_error_list.append(soft_type_i(p_values_combined, alpha = alpha, epsilon = epsilon))
    
    return rho_list, type_i_error_list, p_values_combined
        
