# -*- coding: utf-8 -*-

import sys
from datetime import date
import numpy as np
import time
import gensim
from gensim import models, similarities
from nltk.tokenize import word_tokenize

from multiprocessing.pool import ThreadPool

from operator import attrgetter
import math

import pymysql
import MySQLdb
import re

class NewsAndWeights(object):
    def __init__(self,news,weight=0):
        self.news = news
        self._weight = weight
    def addWeight(self, weight):
        self._weight += weight
    def getNews(self):
        return self.news
    def getWeight(self):
        return self._weight
    def __repr__(self):
        return '{}: {}'.format(self.__class__.__name__,
                                  self._weight)
    def __cmp__(self, other):
        if hasattr(other, 'getKey'):
            return self.getKey().__cmp__(other.getKey())
def load_model():
    model = Doc2Vec.load('./model/news.json.gz.model')
    return model

def makeUpdatedDateNewsList(content,query,weight,topnumber):
    import tfidf
    #Tf-Idf 연산
    docs,doc_names= tfidf.read_doc(content)
    index, inverted_index = tfidf.index_doc(docs,doc_names)
    word_dictionary = tfidf.build_dictionary(inverted_index)
    doc_dictionary = tfidf.build_dictionary(index)
    tfidf_matrix = tfidf.compute_tfidf(index,word_dictionary,doc_dictionary)

    dot = tfidf.query_dot(query,word_dictionary,doc_dictionary)    
    cos = tfidf.cosine_similarity(tfidf_matrix,dot)
    score_matrix = tfidf.dictionary_vector(cos,doc_dictionary)

    #score_matrix = tfidf.score(tfidf_matrix,word_dictionary,doc_dictionary,query)
    #새로 입력된 데이터 기반 뉴스 리스트

    news_weight_list = []
    for news in score_matrix.keys():
        weighted_score = score_matrix[news]
        news_weight_list.append(NewsAndWeights(content[news], weighted_score*weight))
    
    print('\nNewly Updated Data Based :')
    for idx, news_weight in enumerate(news_weight_list[:topnumber]):
        news = news_weight.getNews()
        print("%d." % (idx+1)," %s" % news['date']," %s" % news['title']," %s" % news['category'], " score: %f" % news_weight.getWeight())

    return news_weight_list[:topnumber]

def search(model, content, new_content, query):
    # TODO: 상수값 조정 for 1-2 words
    WEIGHT_SIMILARITY = 4.0
    WEIGHT_CATEGORY = 0.3
    WEIGHT_TERM_FREQUENCY = 0.3
    WEIGHT_LATEST = 2.0
    WEIGHT_ADDNEWEST = 1.0
    WEIGHT_IDF = 1.0

    # TODO: 상수값 조정 for more than 3 words
    WEIGHT_SIMILARITY_L = 4.0
    WEIGHT_CATEGORY_L = 0.3
    WEIGHT_TERM_FREQUENCY_L = 0.3
    WEIGHT_LATEST_L = 2.0
    WEIGHT_ADDNEWEST_L = 1.0
    WEIGHT_IDF_L = 1.0

    if(len(query) > 3): # 4 단어 이상의 쿼리일 때
        WEIGHT_SIMILARITY = WEIGHT_SIMILARITY_L
        WEIGHT_CATEGORY = WEIGHT_CATEGORY_L
        WEIGHT_TERM_FREQUENCY = WEIGHT_TERM_FREQUENCY_L
        WEIGHT_LATEST = WEIGHT_LATEST_L
        WEIGHT_ADDNEWEST = WEIGHT_ADDNEWEST_L
        WEIGHT_IDF = WEIGHT_IDF_L
        print('Inserted Query consis of more than 3 words')

    start = time.clock()

    # N
    pool = ThreadPool(processes=1)
    async_result = pool.apply_async(makeUpdatedDateNewsList, (new_content,query,WEIGHT_ADDNEWEST,5))
    news_weight_list_updated = async_result.get()
    #news_weight_list_updated= makeUpdatedDateNewsList(new_content,query,WEIGHT_ADDNEWEST,5) # 새로운 뉴스 기반 데이터

    # w
    model.random.seed(0)
    infer_vector = model.infer_vector(query)
    similar_docs = model.docvecs.most_similar([infer_vector], topn = 200)
    news_weight_list = makeListAndAddWeightSimilarity(content, similar_docs, WEIGHT_SIMILARITY)
    addWeightTermFrequency(news_weight_list, query, WEIGHT_TERM_FREQUENCY) #input_query: Tokenized 된 쿼리여야 함 ex. ['Trump', 'economy', 'polices']
    addWeightCategory(news_weight_list, content, query, WEIGHT_CATEGORY) #input_query: string 형태 ex. "Trump economy polices"
    addWeightLatest(news_weight_list, content, WEIGHT_LATEST)
    addWeightIDF_Title(news_weight_list, query, WEIGHT_IDF)

    sorted_docs_weight = sorted(news_weight_list, key=attrgetter('_weight'), reverse=True)

    end = time.clock()
    print("Time: ", end-start)

    print('\nDoc2Vec Based :')
    for idx, news_weight in enumerate(sorted_docs_weight[:20]):
        news = news_weight.getNews()
        print("%d." % (idx+1)," %s" % news['date'], " %s" % news['title']," %s" % news['category'], " weight: %f" % news_weight.getWeight())

    # result = w + N
    return sorted_docs_weight,news_weight_list_updated

def makeListAndAddWeightSimilarity(original_data, similar_docs, weight):
    news_weight_list = []
    for idx, s in enumerate(similar_docs):
        similarity = s[1] #similarity
        news = original_data.loc[s[0]] #key of dict: URL of news
        news_weight_list.append(NewsAndWeights(news, similarity * weight))

    return news_weight_list

def addWeightLatest(newsAndWeights, original_data, weight):
    today = date.today()
    for nw in newsAndWeights:
        delta = 1/math.log((today-nw.news['date']).days)*weight*10
        nw.addWeight(delta)
    return

def addWeightCategory(newsAndWeights, content, input_query, weight):
    import classifier
    string_query = ""
    for query in input_query:
        string_query += query + " "
    predicted_category = classifier.predict_category(content, [string_query])
    for nw in newsAndWeights:
        if nw.news['category'] == predicted_category[0]:
            nw.addWeight(weight)
    return

def addWeightTermFrequency(newsAndWeights, input_query, weight):
    from nltk.corpus import stopwords
    stopwrds = stopwords.words('english')
    
    query_removed_stopwords = [token for token in input_query if token not in stopwrds]

    for terms in query_removed_stopwords:
        for nw in newsAndWeights:
            count = nw.news['title'].count(terms) + nw.news['article'].count(terms)
            nw.addWeight(count * weight)
    return

def addWeightIDF_Title(newsAndWeights, input_query, weight):
    from nltk.corpus import stopwords
    stopwrds = stopwords.words('english')
    
    query_removed_stopwords = [token for token in input_query if token not in stopwrds]
    conn = pymysql.connect(host='localhost', user='root', password='root', db='Crawled_Data', charset='utf8')

    word_Df={}
    for word in query_removed_stopwords:
        curs = conn.cursor(pymysql.cursors.DictCursor)
        sql_query = "select number from Df Where word ='"+word+"'"
        curs.execute(sql_query)
        data = curs.fetchall()
        if not (type(data)==tuple ): 
            word_Df[word] = data[0]['number']
        else :
            word_Df[word] = 1 
        # // db랑 연결 끊음
    conn.close()

    for terms in query_removed_stopwords:
        for nw in newsAndWeights:
            wordlist = word_tokenize(re.sub('[!"#%\'()*+,./:;<=>?\[\]\\xa0^_`{|}~’”“′‘\\\]',' ', nw.news['title'].lower()))
            for word in wordlist:
                if (word in word_Df.keys()):
                    value_of_df = 1/ (word_Df[word]) *10000
                    nw.addWeight(value_of_df * weight)
    return
# TODO:
def addNewsToWeightList(original_data,givenlist,weight):
    news_weight_list = givenlist
    for url in original_data.keys():
        news=original_data.loc[url]
        news_weight_list.append(NewsAndWeights(news,weight))
    return news_weight_list

'''
if __name__ == "__main__":
    input_query = get_argument()
    print('Input query : ', input_query)

    content = read_JSON('./data/NC_70mb.json.gz')
    new_content = read_JSON('./data/NC_s.txt.gz')
    search(content, new_content, input_query)
'''
