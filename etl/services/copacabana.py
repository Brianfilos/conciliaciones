from etl.services.base import ProcesadorBase


class ProcesadorCopacabana(ProcesadorBase):
    PREFIJO      = "903"
    CSV_SEP      = ","
    CONSEC_COL   = "Consecutivo 1"
    CENTRO       = "1501"
    CONCEPTO_IND_AUTO = "10154"
    CONCEPTO_COM_AUTO = "10156"
    CONCEPTO_SER_AUTO = "10155"
    CONCEPTO_IND_RETE = "10154"
    CONCEPTO_COM_RETE = "10156"
    CONCEPTO_SER_RETE = "10155"
    CONCEPTO_IND_DEC  = "10144"
    CONCEPTO_COM_DEC  = "01100"
    CONCEPTO_SER_DEC  = "10145"
    CONCEPTO_SAN = "10112"
    CONCEPTO_INT = "10113"
    CONCEPTO_EXC = "10153"
    CONCEPTO_EXC_RETE = "10153"
    CONCEPTO_TAR = "10157"
