"""The models module defines functions to create spacy models."""
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

import omegaconf
import spacy
from camphr.lang.torch import TorchLanguage
from camphr.ner_labels.utils import get_biluo_labels
from camphr.pipelines.trf_model import TRANSFORMERS_MODEL
from camphr.pipelines.trf_ner import TRANSFORMERS_NER
from camphr.pipelines.trf_seq_classification import TRANSFORMERS_SEQ_CLASSIFIER
from camphr.pipelines.trf_tokenizer import TRANSFORMERS_TOKENIZER
from camphr.pipelines.trf_utils import LABELS
from camphr.utils import get_labels
from cytoolz import merge
from omegaconf import OmegaConf
from spacy.language import Language
from spacy.vocab import Vocab


@dataclass
class LangConfig(omegaconf.Config):
    name: str
    torch: bool
    optimizer: Dict[str, Any]
    kwargs: Optional[Dict[str, Any]]


@dataclass
class NLPConfig(omegaconf.Config):
    name: str
    lang: LangConfig
    pipeline: omegaconf.DictConfig


def create_lang(cfg: LangConfig) -> Language:
    kwargs = cfg.kwargs or {}
    kwargs = (
        OmegaConf.to_container(kwargs)
        if isinstance(kwargs, omegaconf.Config)
        else kwargs
    )
    if cfg.torch:
        kwargs["meta"] = merge(kwargs.get("meta", {}), {"lang": cfg.name})
        return TorchLanguage(Vocab(), optimizer_config=cfg.optimizer, **kwargs)
    return spacy.blank(cfg.name, **kwargs)


def create_model(cfg: Union[NLPConfig, Any]) -> Language:
    if not isinstance(cfg, omegaconf.Config):
        cfg = OmegaConf.create(cfg)
    cfg = correct_nlp_config(cfg)
    nlp = create_lang(cfg.lang)
    for name, config in cfg.pipeline.items():
        if config:
            config = OmegaConf.to_container(config)
        nlp.add_pipe(nlp.create_pipe(name, config=config or dict()))
    if cfg.name and isinstance(cfg.name, str):
        nlp._meta["name"] = cfg.name
    return nlp


def correct_nlp_config(cfg: NLPConfig) -> NLPConfig:
    cfg = _correct_trf_pipeline(cfg)
    cfg = _resolve_label(cfg)
    return cfg


def _correct_trf_pipeline(cfg: NLPConfig) -> NLPConfig:
    """Correct config for transformers pipeline

    Note:
        1. Complement missing pipeline.

            For example, `transformers_ner` requires `transformers_model` and `transformers_tokenizer`.
            If they are missed, assign them to config.

        2. Complement `trf_name_or_path` for transformers pipelines.
        3. If there are trf pipe in pipeline, set lang.torch = true
    """
    cfg = _complement_trf_pipeline(cfg)
    cfg = _complement_trf_name(cfg)
    cfg = _correct_torch(cfg)
    return cfg


TRF_BASES = [TRANSFORMERS_TOKENIZER, TRANSFORMERS_MODEL]
TRF_TASKS = [TRANSFORMERS_SEQ_CLASSIFIER, TRANSFORMERS_NER]
TRF_PIPES = TRF_BASES + TRF_TASKS


def _complement_trf_pipeline(cfg: NLPConfig) -> NLPConfig:
    pipe_names = list(cfg.pipeline.keys())
    trf_task_indices = [pipe_names.index(k) for k in TRF_TASKS if k in pipe_names]
    if not trf_task_indices:
        # No transformers task pipes
        return cfg
    trf_task_idx = min(trf_task_indices)
    for k in reversed(TRF_BASES):
        if k not in pipe_names:
            pipe_names.insert(trf_task_idx, k)
    cfg.pipeline = {k: cfg.pipeline.get(k, {}) for k in pipe_names}
    return cfg


def _complement_trf_name(cfg: NLPConfig) -> NLPConfig:
    KEY = "trf_name_or_path"
    VAL = ""
    if not set(cfg.pipeline.keys()) & set(TRF_PIPES):
        return cfg
    for k, v in cfg.pipeline.items():
        if k in TRF_PIPES and v[KEY]:
            VAL = v[KEY]
    if not VAL:
        raise ValueError(
            f"Invalid configuration. At least one of transformer's pipe needs `{KEY}`, but the configuration is:\n"
            + cfg.pipeline.pretty()
        )
    for k, v in cfg.pipeline.items():
        if k in TRF_PIPES:
            v[KEY] = VAL
    return cfg


def _resolve_label(cfg: NLPConfig) -> NLPConfig:
    ner = cfg.pipeline[TRANSFORMERS_NER]
    if ner:
        ner[LABELS] = get_biluo_labels(ner[LABELS])
    seq = cfg.pipeline[TRANSFORMERS_SEQ_CLASSIFIER]
    if seq:
        seq[LABELS] = get_labels(seq[LABELS])
    return cfg


def _correct_torch(cfg: NLPConfig) -> NLPConfig:
    if set(cfg.pipeline) & set(TRF_PIPES):
        cfg.lang.torch = True
    return cfg
