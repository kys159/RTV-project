#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 17-4-27 下午8:44
# @Author  : Tianyu Liu

import sys
import os
import tensorflow as tfss
import time
from SeqUnit import *
from DataLoader import DataLoader
import numpy as np
from rouge_score import rouge_scorer
from nltk.translate.bleu_score import corpus_bleu, SmoothingFunction
from preprocess import *
from util import * 
import time
# import wandb
# wandb.init()

tf.app.flags.DEFINE_integer("hidden_size", 500, "Size of each layer.")
tf.app.flags.DEFINE_integer("emb_size", 400, "Size of embedding.")
tf.app.flags.DEFINE_integer("field_size", 50, "Size of embedding.")
tf.app.flags.DEFINE_integer("pos_size", 5, "Size of embedding.")
tf.app.flags.DEFINE_integer("batch_size", 128, "Batch size of train set.")
tf.app.flags.DEFINE_integer("epoch", 1000, "Number of training epoch.")
tf.app.flags.DEFINE_integer("source_vocab", 471,'vocabulary size')
#tf.app.flags.DEFINE_integer("source_vocab", 20003,'vocabulary size')
tf.app.flags.DEFINE_integer("field_vocab", 42,'vocabulary size')
#tf.app.flags.DEFINE_integer("field_vocab", 1480,'vocabulary size')
tf.app.flags.DEFINE_integer("position_vocab", 31,'vocabulary size')
tf.app.flags.DEFINE_integer("target_vocab", 471,'vocabulary size')
#tf.app.flags.DEFINE_integer("target_vocab", 20003,'vocabulary size')
tf.app.flags.DEFINE_integer("report", 4,'report valid results after some steps')
#tf.app.flags.DEFINE_integer("report", 18209,'report valid results after some steps')
tf.app.flags.DEFINE_float("learning_rate", 0.0003,'learning rate')

tf.app.flags.DEFINE_string("mode",'train','train or test')
#tf.app.flags.DEFINE_string("mode",'test','train or test')
#tf.app.flags.DEFINE_string("load",'1628077267029','load directory') # BBBBBESTOFAll
tf.app.flags.DEFINE_string("load",'0','load directory') # BBBBBESTOFAll
tf.app.flags.DEFINE_string("dir",'processed_data','data set directory')
tf.app.flags.DEFINE_integer("limits", 0,'max data set size')


tf.app.flags.DEFINE_boolean("dual_attention", True,'dual attention layer or normal attention')
tf.app.flags.DEFINE_boolean("fgate_encoder", True,'add field gate in encoder lstm')

tf.app.flags.DEFINE_boolean("field", True,'concat field information to word embedding')
tf.app.flags.DEFINE_boolean("position", True,'concat position information to word embedding')
tf.app.flags.DEFINE_boolean("encoder_pos", True,'position information in field-gated encoder')
tf.app.flags.DEFINE_boolean("decoder_pos", True,'position information in dual attention decoder')


FLAGS = tf.app.flags.FLAGS
# wandb.config.update(FLAGS)
last_best = 0.0

gold_path_test = 'processed_data/test/test_split_for_rouge/gold_summary_'
gold_path_valid = 'processed_data/valid/valid_split_for_rouge/gold_summary_'

# test phase
if FLAGS.load != "0":
    save_dir = 'results/res/' + FLAGS.load + '/'
    save_file_dir = save_dir + 'files/'
    pred_dir = 'results/evaluation/' + FLAGS.load + '/'
    if not os.path.exists(pred_dir):
        os.mkdir(pred_dir)
    if not os.path.exists(save_file_dir):
        os.mkdir(save_file_dir)
    pred_path = pred_dir + 'pred_summary_'
    pred_beam_path = pred_dir + 'beam_summary_'
# train phase
else:
    prefix = str(time.strftime('%Y%m%d_%H%M'))
    save_dir = 'results/res/' + prefix + '/'
    save_file_dir = save_dir + 'files/'
    pred_dir = 'results/evaluation/' + prefix + '/'
    os.mkdir(save_dir)
    if not os.path.exists(pred_dir):
        os.mkdir(pred_dir)
    if not os.path.exists(save_file_dir):
        os.mkdir(save_file_dir)
    pred_path = pred_dir + 'pred_summary_'
    pred_beam_path = pred_dir + 'beam_summary_'

log_file = save_dir + 'log.txt'


def train(sess, dataloader, model):
    write_log("#######################################################")
    for flag in FLAGS.__flags:
        write_log(flag + " = " + str(FLAGS.__flags[flag]))
    write_log("#######################################################")
    trainset = dataloader.train_set
    k = 0
    loss, start_time = 0.0, time.time()
    for n_ep in range(FLAGS.epoch):
        print("epoch : {}".format(n_ep+1))        
        for x in dataloader.batch_iter(trainset, FLAGS.batch_size, True):
            loss += model(x, sess)
            k += 1
            progress_bar(k%FLAGS.report, FLAGS.report)
            if (k % FLAGS.report == 0):                
                cost_time = time.time() - start_time
                write_log("%d : loss = %.3f, time = %.3f " % (k // FLAGS.report, loss, cost_time))
                loss, start_time = 0.0, time.time()
                if k // FLAGS.report >= 1: 
                    ksave_dir = save_model(model, save_dir, k // FLAGS.report)
                    write_log(evaluate(sess, dataloader, model, ksave_dir, 'valid'))
        


def test(sess, dataloader, model):
    evaluate(sess, dataloader, model, save_dir, 'test')

def save_model(model, save_dir, cnt):
    new_dir = save_dir + 'loads' + '/' 
    if not os.path.exists(new_dir):
        os.mkdir(new_dir)
    nnew_dir = new_dir + str(cnt) + '/'
    if not os.path.exists(nnew_dir):
        os.mkdir(nnew_dir)
    model.save(nnew_dir)
    return nnew_dir

def evaluate(sess, dataloader, model, ksave_dir, mode='valid'):
    if mode == 'valid':
        # texts_path = "original_data/valid.summary"
        texts_path = "processed_data/valid/valid.box.val"
        gold_path = gold_path_valid
        evalset = dataloader.dev_set
    else:
        # texts_path = "original_data/test.summary"
        texts_path = "processed_data/test/test.box.val"
        gold_path = gold_path_test
        evalset = dataloader.test_set
    
    # for copy words from the infoboxes
    texts = open(texts_path, 'rt', encoding = "UTF8").read().strip().split('\n')
    texts = [list(t.strip().split()) for t in texts]
    v = Vocab()

    # with copy
    pred_list, pred_list_copy, gold_list = [], [], []
    pred_unk, pred_mask = [], []
    
    k = 0
    for x in dataloader.batch_iter(evalset, FLAGS.batch_size, False):
        predictions, atts = model.generate(x, sess)
        atts = np.squeeze(atts)
        idx = 0
        for summary in np.array(predictions):
            with open(pred_path + str(k), 'w', -1, "utf-8") as sw:
                summary = list(summary)
                if 2 in summary:
                    summary = summary[:summary.index(2)] if summary[0] != 2 else [2]
                real_sum, unk_sum, mask_sum = [], [], []
                for tk, tid in enumerate(summary):
                    if tid == 3:
                        sub = texts[k][np.argmax(atts[tk,: len(texts[k]),idx])]
                        real_sum.append(sub)
                        mask_sum.append("**" + str(sub) + "**")
                    else:
                        real_sum.append(v.id2word(tid))
                        mask_sum.append(v.id2word(tid))
                    unk_sum.append(v.id2word(tid))
                sw.write(" ".join([str(x) for x in real_sum]) + '\n')
                pred_list.append([str(x) for x in real_sum])
                pred_unk.append([str(x) for x in unk_sum])
                pred_mask.append([str(x) for x in mask_sum])
                k += 1
                idx += 1
    write_word(pred_mask, ksave_dir, mode + "_summary_copy.txt")
    write_word(pred_unk, ksave_dir, mode + "_summary_unk.txt")


    for tk in range(k):
        with open(gold_path + str(tk), 'r', -1, "utf-8") as g:
            gold_list.append([g.read().strip().split()])

    gold_set = [[gold_path + str(i)] for i in range(k)]
    pred_set = [pred_path + str(i) for i in range(k)]

    # recall_tmp, precision_tmp, F_measure_tmp = [],[],[]
    # scorer = rouge_scorer.RougeScorer(['rouge1'])
    # for i in range(len(pred_set)) :
    #     pred = open(pred_set[i], "rt", encoding="UTF8")
    #     pred_lines = pred.readlines()
    #     gold = open(gold_set[i][0], "rt", encoding="UTF8")
    #     gold_lines = gold.readlines()
        
    #     scores = scorer.score(pred_lines[0], gold_lines[0])
    #     result = list(scores.values())

    #     recall_tmp.append(result[0][1])
    #     precision_tmp.append(result[0][0])
    #     F_measure_tmp.append(result[0][2])

    # recall = np.mean(recall_tmp)
    # precision = np.mean(precision_tmp)
    # F_measure = np.mean(F_measure_tmp)

    F_measure1_tmp, F_measure2_tmp, F_measure3_tmp = [],[],[]
    scorer1 = rouge_scorer.RougeScorer(['rouge1'])
    scorer2 = rouge_scorer.RougeScorer(['rouge2'])
    scorer3 = rouge_scorer.RougeScorer(['rouge3'])

    for i in range(len(pred_set)) :
        pred = open(pred_set[i], "rt", encoding="UTF8")
        pred_lines = pred.readlines()
        gold = open(gold_set[i][0], "rt", encoding="UTF8")
        gold_lines = gold.readlines()
        
        scores1 = scorer1.score(pred_lines[0], gold_lines[0])
        scores2 = scorer2.score(pred_lines[0], gold_lines[0])
        scores3 = scorer3.score(pred_lines[0], gold_lines[0])
        result1 = list(scores1.values())
        result2 = list(scores2.values())
        result3 = list(scores3.values())

        F_measure1_tmp.append(result1[0][2])
        F_measure2_tmp.append(result2[0][2])
        F_measure3_tmp.append(result3[0][2])

    F_measure1 = np.mean(F_measure1_tmp)
    F_measure2 = np.mean(F_measure2_tmp)
    F_measure3 = np.mean(F_measure3_tmp)

    bleu = corpus_bleu(gold_list, pred_list)
    # copy_result = "with copy F_measure: %s Recall: %s Precision: %s BLEU: %s\n" % \
    # (str(F_measure), str(recall), str(precision), str(bleu))
    copy_result = "with copy F_measure of ROUGE1: %s ROUGE2: %s ROUGE3: %s BLEU: %s\n" % \
    (str(F_measure1), str(F_measure2), str(F_measure3), str(bleu))
    # print copy_result

    # for tk in range(k):
    #     with open(pred_path + str(tk), 'w', -1 ,"utf-8") as sw:
    #         sw.write(" ".join(pred_unk[tk]) + '\n')

    # bleu = corpus_bleu(gold_list, pred_unk)
    # # nocopy_result = "without copy F_measure: %s Recall: %s Precision: %s BLEU: %s\n" % \
    # # (str(F_measure), str(recall), str(precision), str(bleu))
    # nocopy_result = "without copy F_measure of ROUGE1: %s ROUGE2: %s ROUGE3: %s BLEU: %s\n" % \
    # (str(F_measure1), str(F_measure2), str(F_measure3), str(bleu))

    # print nocopy_result
    result = copy_result #+ nocopy_result 
    # print result
    if mode == 'valid':
        print (result)
    # wandb.log({'F_measure1' : F_measure1, 'F_measure2' : F_measure2, 'F_measure3' : F_measure3, 'BLEU' : bleu})
    return result



def write_log(s):
    print (s)
    with open(log_file, 'a') as f:
        f.write(s+'\n')


def main():
    config = tf.compat.v1.ConfigProto(allow_soft_placement=True) ## tf.ConfigProto(allow_soft_placement=True)
    config.gpu_options.allow_growth = True
    with tf.compat.v1.Session(config=config) as sess:  ## tf.Session(config=config) as sess:
        # copy_file(save_file_dir)
        dataloader = DataLoader(FLAGS.dir, FLAGS.limits)
        model = SeqUnit(batch_size=FLAGS.batch_size, hidden_size=FLAGS.hidden_size, emb_size=FLAGS.emb_size,
                        field_size=FLAGS.field_size, pos_size=FLAGS.pos_size, field_vocab=FLAGS.field_vocab,
                        source_vocab=FLAGS.source_vocab, position_vocab=FLAGS.position_vocab,
                        target_vocab=FLAGS.target_vocab, scope_name="seq2seq", name="seq2seq",
                        field_concat=FLAGS.field, position_concat=FLAGS.position,
                        fgate_enc=FLAGS.fgate_encoder, dual_att=FLAGS.dual_attention, decoder_add_pos=FLAGS.decoder_pos,
                        encoder_add_pos=FLAGS.encoder_pos, learning_rate=FLAGS.learning_rate)
        sess.run(tf.compat.v1.global_variables_initializer())
        # copy_file(save_file_dir)
        if FLAGS.load != '0':
            model.load(save_dir)
        if FLAGS.mode == 'train':
            train(sess, dataloader, model)
        else:
            test(sess, dataloader, model)


if __name__=='__main__':
    with tf.device('/gpu:1'):
        main()
