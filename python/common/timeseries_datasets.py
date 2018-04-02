import numpy as np
import pandas as pd
# from pandas import datetime
from common.utils import *


class TsFileDef(object):
    def __init__(self, path, usecols, date_columns, index_column, ARIMA_order):
        self.path = path
        self.usecols = usecols
        self.date_columns = date_columns
        self.index_column = index_column
        self.ARIMA_order = ARIMA_order


# def date_parser(x):
#     # date parser for shampoo dataset
#     return datetime.strptime('190'+x, '%Y-%m')


univariate_timeseries_datasets = {
    # "name": (path, use_cols, date_columns, index_column, ARIMA_order)
    "airline": TsFileDef("AirlinePassengers/international-airline-passengers.csv", [1], False, None, (4, 1, 1)),
    "aus_beer": TsFileDef("AustralianBeerProduction/quarterly-beer-production-in-aus.csv", [2], False, None, (4, 1, 0)),
    "lynx": TsFileDef("CanadianLynx/lynx_trappings.csv", [1], False, None, (4, 1, 0)),
    "fisher_temp": TsFileDef("FisherRiver/mean-daily-temperature-fisher-ri.csv", [1], False, None, (4, 1, 0)),
    "shampoo": TsFileDef("ShampooSales/sales-of-shampoo-over-a-three-ye.csv", [1], [0], None, (5, 1, 0)),
    "us_accident": TsFileDef("USAccidentalDeaths/accidental-deaths-in-usa-monthly.csv", [1], False, None, (4, 1, 0)),
    "wolf_sunspot": TsFileDef("WolfSunSpot/wolfs-sunspot-numbers-1700-1988.csv", [1], False, None, (4, 1, 0))
}


def get_univariate_timeseries_data(dataset):
    dataset_def = univariate_timeseries_datasets[dataset]
    data = pd.read_csv("../datasets/%s" % dataset_def.path,
                       header=0, sep=",", usecols=dataset_def.usecols,
                       # parse_dates=dataset_def.date_columns, index_col=dataset_def.index_column,
                       # squeeze=True, date_parser=date_parser
                       )
    return data


def difference_series(series, interval=1):
    n, m = series.shape
    diffs = np.zeros((n-interval, m), dtype=series.dtype)
    for i in range(interval, n):
        diffs[i-interval, :] = series[i, :] - series[i-interval, :]
    return diffs


def invert_difference_series_old(history, series, interval=1):
    n, m = series.shape
    inv = np.zeros((n, m), dtype=series.dtype)
    for i in range(n):
        inv[i, :] = series[i, :] + history[i, :]
    return inv


def invert_difference_series(series, initial, interval=1):
    n, m = series.shape
    inv = np.zeros((n, m), dtype=series.dtype)
    prev = initial
    for i in range(n):
        prev = series[i, :] + prev
        inv[i, :] = prev
    return inv


class TSeries(object):
    """ Provides simple APIs for iterating over a timeseries and activities """
    def __init__(self, samples, y=None, activities=None, starts=None, name=None):
        self.samples = samples
        self.y = y
        self.series_len = self.samples.shape[0]
        self.dim = self.samples.shape[1]
        self.activities = activities
        self.starts = starts
        self.name = name

        if self.y is None and self.activities is not None and self.starts is not None:
            # populate the activity labels
            n = self.samples.shape[0]
            n_acts = self.activities.shape[0]
            self.y = np.zeros(shape=(n, 1), dtype=int)
            for i in range(n_acts):
                s = self.starts[i, 0]
                e = n if i == n_acts-1 else self.starts[i+1, 0]
                self.y[s:e, 0] = self.activities[i, 0]

    def get_batches(self, n_lags, batch_size, single_output_only=False):
        """ Iterate over timeseries where current values are functions of previous values

        The assumption is that the model is:
            (y_{t-n_lag+1}, y_{t}, y_{t+1},...) = f(x_{t-n_lag+1}, x_{t-1}, x_t,...)

        Args:
            n_lags: int
            batch_size: int
            single_output_only: boolean
                True:
                    Return only the current y-value for each time point.
                    This is useful when predicting only the last y-value
                False:
                    Return n_lags y-values for each time point

        returns: np.ndarray(shape=(batch_size, n_lags, d))
            where d = samples.shape[1]
            The data is ordered in increasing time
        """
        n = self.samples.shape[0]
        d_in = self.samples.shape[1]
        d_out = 0 if self.y is None else self.y.shape[1]
        batch_size = n if batch_size < 0 else batch_size
        for i in xrange(0, n, batch_size):
            x = np.zeros(shape=(batch_size, n_lags, d_in), dtype=np.float32)
            y = None
            if self.y is not None and not single_output_only:
                y = np.zeros(shape=(batch_size, n_lags, d_out), dtype=np.float32)
            e = min(n, i + batch_size)
            sz = e - i
            # logger.debug("i, e, sz: %d, %d, %d" % (i, e, sz))
            for t in range(n_lags):
                st = max(0, i - t)  # maximum time we can go back in the past
                et = e - t
                # logger.debug("st, et: %d, %d" % (st, et))
                if et >= st:
                    x[(sz-(et-st)):sz, n_lags - 1 - t, :] = self.samples[st:et, :]
                    if y is not None and not single_output_only:
                        y[(sz - (et - st)):sz, n_lags - 1 - t, :] = self.y[st:et, :]
                else:
                    break
            if self.y is not None and single_output_only:
                y = self.y[i:e, :]
            elif y is not None:
                y = y[0:sz, :, :]
            yield x[0:sz, :, :], y

    def get_shingles(self, window_size, skip_size=None, batch_size=100):
        """ Creates feature vectors out of windows of data and iterates over these

        The instances are of the form:
            (x_{t-window_size+1}, ..., x_t)

        returns: np.ndarray(shape=(batch_size, n_lags, d))
            where d = samples.shape[1]
        """
        skip_size = window_size if skip_size is None else skip_size
        n = self.samples.shape[0]
        d = self.samples.shape[1]
        if batch_size < 0:
            batch_size = 1 + n // skip_size
        x = np.zeros(shape=(batch_size, window_size, d), dtype=np.float32)
        w = np.zeros(batch_size, dtype=np.int)  # window start time
        y = None
        if self.y is not None: y = np.zeros(batch_size, dtype=np.int)
        l = 0
        for i in xrange(0, n, skip_size):
            et = min(n - i, window_size)
            x[l, 0:et, :] = self.samples[i:(i+et), :]
            w[l] = i
            if self.y is not None:
                y[l] = self.y[i]
            l += 1
            if l == batch_size or i + skip_size >= n:
                x_, y_, w_ = x, y, w
                if l < batch_size:
                    x_, y_, w_ = x[0:l, :, :], None if y is None else y[0:l], w[0:l]
                yield x_, y_, w_
                if i + skip_size < n:
                    l = 0
                    x = np.zeros(shape=(batch_size, window_size, d), dtype=np.float32)
                    w = np.zeros(batch_size, dtype=np.int)
                    if self.y is not None: y = np.zeros(batch_size, dtype=np.int)

    def log_batches(self, n_lags, batch_size, single_output_only=False):
        """ Debug API """
        logger.debug("Logging timeseries (nlags: %d, batch_size: %d)" % (n_lags, batch_size))
        i = 0
        for x, y in self.get_batches(n_lags, batch_size, single_output_only=single_output_only):
            logger.debug("x: (%s), y: (%s)" % (str(x.shape), "-" if y is None else str(y.shape)))
            if y is not None:
                # logger.debug("y[%d](%d)\n%s" % (i, y.shape[0], str(np.reshape(y, newshape=(-1,)))))
                if single_output_only:
                    batch = np.hstack([y, np.reshape(x, newshape=(x.shape[0],-1))])
                else:
                    batch = np.hstack([np.reshape(y, newshape=(y.shape[0],-1)), np.reshape(x, newshape=(x.shape[0], -1))])
            else:
                batch = x
            logger.debug("batch[%d](%d)\n%s" % (i, x.shape[0], str(np.round(batch, 3))))
            i += 1


def prepare_tseries(series, name=""):
    x = series[:-1]
    y = series[1:]
    return TSeries(x, y=y, name=name)