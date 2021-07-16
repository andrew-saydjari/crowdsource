import warnings
from astropy.io import fits
from astropy.utils.exceptions import AstropyWarning
from astropy.modeling.models import Ellipse2D
from astropy.wcs import Wcsprm, WCS
from astropy.coordinates import SkyCoord
from pydl.pydlutils import spheregroup
import numpy as np

def galaxy_mask(header,leda):
    racen = header["CRVAL1"]
    deccen = header["CRVAL2"]
    c = SkyCoord(racen, deccen, frame='icrs', unit='deg')
    sz = (header["NAXIS1"], header["NAXIS2"])
    outmsk = np.zeros((sz[0],sz[1]),dtype=bool)

    ra, dec, theta, diam, ba = leda

    ##CCD corners (these are actually in the header for DECam)
    xc = [0,0,sz[0]-1,sz[0]-1]
    yc = [0,sz[1]-1,0,sz[1]-1]

    w = WCS(header)
    sep = c.separation(w.pixel_to_world(xc, yc))

    dac = np.max(sep.degree)
    coordleda = SkyCoord(ra,dec,frame='icrs',unit='deg')
    dangle = c.separation(coordleda).degree

    keep = dangle < dac + diam
    #filter out galaxies with too large angle displace to consider
    if sum(keep) == 0:
        return outmsk

    relevant = w.world_to_pixel(coordleda[keep])

    with warnings.catch_warnings():
        warnings.simplefilter('ignore', category=[AstropyWarning,RuntimeWarning])
        wperm = Wcsprm(header=header.tostring().encode('utf-8'))
        cd = wperm.cd * wperm.cdelt[np.mod(np.linspace(0,3,4,dtype=int),2).reshape(2,2)]
    pscl = np.mean(np.sqrt(np.sum(cd**2,axis=1)))*3600 #convert back to arcsec from deg for interp
    msz = np.ceil(3600*diam[keep]/pscl).astype(int) #this is the mask size in the pixel scale
    msz += np.mod(msz,2) == 0 #adjust even size to be odd so that the center means something
    mh = (msz-1)//2 #I think this -1 is necessary becase we are all odd by construction

    ix = np.round(relevant[0]).astype(int)
    iy = np.round(relevant[1]).astype(int)

    #largest circle approx must fall in ccd
    insideim = ((ix+mh) >= 0) & ((ix-mh) < sz[0]) & ((iy+mh) >= 0) & (iy-mh < sz[1])
    nim = sum(insideim)

    #filter out galaxy with no overlap
    if nim == 0:
        return outmsk

    rainl = coordleda[keep][insideim].ra.degree
    decinl = coordleda[keep][insideim].dec.degree
    thetal = np.deg2rad(theta[keep][insideim])

    print("Masked Galaxies: %d" % nim)
    for i in range(0,nim):
        un, ue = tan_unit_vectors(rainl[i],decinl[i],racen,deccen)

        ueofn = un*np.cos(thetal[i])+ue*np.sin(thetal[i])
        angle = np.rad2deg(np.arctan2(ueofn[1],ueofn[0]))

        ixn = ix[insideim][i]
        iyn = iy[insideim][i]
        mhn = mh[insideim][i]
        mszn = msz[insideim][i]

        e = Ellipse2D(x_0=mhn, y_0=mhn, a=mhn, b=ba[keep][insideim][i]*mhn,
                      theta=np.deg2rad(angle))
        y, x = np.mgrid[0:mszn, 0:mszn]
        smsk = (e(x, y) == 1)

        outmsk[np.clip(ixn-mhn,a_min=0,a_max=None):np.clip(ixn+mhn,a_min=None,a_max=sz[0]-1),
           np.clip(iyn-mhn,a_min=0,a_max=None):np.clip(iyn+mhn,a_min=None,a_max=sz[1]-1)] |= smsk[
        np.clip(mhn-ixn,a_min=0,a_max=None):np.clip(sz[0]-ixn+mhn-1,a_min=None,a_max=mszn-1),
             np.clip(mhn-iyn,a_min=0,a_max=None):np.clip(sz[1]-iyn+mhn-1,a_min=None,a_max=mszn-1)]
    return outmsk

def tan_unit_vectors(rain,decin,l0,p0):
    # handle the poles
    if p0 == 90:
        l0 = 180
    elif p0 == -90:
        l0 = 0

    lambda0, phi0, lambda1, phi1  = np.deg2rad([l0,p0,rain,decin])

    cosc = np.sin(phi0)*np.sin(phi1)+np.cos(phi0)*np.cos(phi1)*np.cos(lambda1-lambda0)

    dx_dphi = (-np.sin(phi1)*(np.sin(lambda1-lambda0)/cosc) -
            (np.sin(lambda1-lambda0)*np.cos(phi1)*(np.sin(phi0)*np.cos(phi1) -
            np.cos(phi0)*np.sin(phi1)*np.cos(lambda1-lambda0)))*(cosc**(-2)))*(-1)

    dy_dphi = (1/cosc)*(np.cos(phi0)*np.cos(phi1) +
            np.sin(phi0)*np.sin(phi1)*np.cos(lambda1-lambda0)) - \
            (np.cos(phi0)*np.sin(phi1) - \
            np.sin(phi0)*np.cos(phi1)*np.cos(lambda1-lambda0))*(np.sin(phi0)*np.cos(phi1) -
            np.cos(phi0)*np.sin(phi1)*np.cos(lambda1-lambda0))*(cosc**(-2))

    dx_dlambda = -1*((np.cos(phi1)*np.cos(lambda1-lambda0)/cosc) +
               ((np.cos(phi1))**2)*((np.sin(lambda1-lambda0))**2)*(cosc**(-2)))

    dy_dlambda = (np.sin(phi0)*np.cos(phi1)*np.sin(lambda1-lambda0)/cosc) + \
               (np.cos(phi0)*np.sin(phi1)-np.sin(phi0)*np.cos(phi1)*np.cos(lambda1 -
               lambda0))*np.cos(phi0)*np.cos(phi1)*np.sin(lambda1-lambda0)*(cosc**(-2))

    norm_phi = np.sqrt(dx_dphi**2+dy_dphi**2)
    norm_lambda = np.sqrt(dx_dlambda**2+dy_dlambda**2)

    un = np.array([dx_dphi/norm_phi, dy_dphi/norm_phi])
    ue = np.array([dx_dlambda/norm_lambda, dy_dlambda/norm_lambda])
    return un, ue

def read_leda_decaps(fname = "/n/home12/saydjari/finksagescratch/Working/2021_07_15/leda_decaps.fits"):
    leda = fits.getdata(fname,1)
    ra = leda["ra"]
    dec = leda["dec"]
    theta = leda["theta"]# degrees 0->180
    diam = leda["diam"] #deg
    ba = leda["ba"]
    return [ra, dec, theta, diam, ba]

def read_leda(fname = "/n/home13/schlafly/misc/leda-logd25-0.05.fits.gz"):
    leda = fits.getdata(fname,1)
    ra = leda["RA"]
    dec = leda["DEC"]
    theta = leda["PA"]# degrees 0->180
    diam = leda["D25"]/3600.0 #convert arcsec to deg
    ba = leda["BA"]
    ba[ba <= 0] = 1.0 #circular if not avail
    #theta = -999 is not present in our usual catalogue
    ba[theta == -999] = 1.0 #circular if no PA available
    theta[theta == -999] = 0.0 #default is to assume no orientation
    return ra, dec, theta, diam, ba

def clean_leda(fname = "/n/home13/schlafly/misc/leda-logd25-0.05.fits.gz"):
    ra, dec, theta, diam, ba = read_leda(fname = "/n/home13/schlafly/misc/leda-logd25-0.05.fits.gz")
    import csv

    ## hand removed galaxy list
    frm = '/n/home12/saydjari/finksagescratch/Working/2021_07_15/hyperleda_to_remove.csv'
    with open(frm, newline='') as csvfile:
        data_rm = np.array(list(csv.reader(csvfile,quoting=csv.QUOTE_NONNUMERIC)))

    ra_bad = data_rm[:,0]
    dec_bad = data_rm[:,1]
    sphout = spheregroup.spherematch(ra_bad,dec_bad,ra,dec,1.0/3600.0)

    assert ra_bad.shape[0] == sphout[0].shape[0]
    assert np.max(sphout[2]) <= 1e-7

    mask1d = np.ones(ra.shape,dtype=bool)
    mask1d[sphout[1]] = False

    #drop all the hand removed galaxies
    ra = ra[mask1d]
    dec = dec[mask1d]
    theta = theta[mask1d]
    diam = diam[mask1d]
    ba = ba[mask1d]

    ## by eye modified galaxy sizes list
    fmod = '/n/home12/saydjari/finksagescratch/Working/2021_07_15/hyperleda_custom_sizes.csv'
    with open(fmod, newline='') as csvfile:
        data_mod = np.array(list(csv.reader(csvfile,quoting=csv.QUOTE_NONNUMERIC)))

    ra_mod = data_mod[:,0]
    dec_mod = data_mod[:,1]
    diam_mod = data_mod[:,2]

    sphout = spheregroup.spherematch(ra_mod,dec_mod,ra,dec,1.0/3600.0)

    assert ra_bad1.shape[0] == sphout1[2].shape[0]
    assert np.max(sphout1[2]) <= 1e-7

    diam[sphout1[1]] = diam_mod[sphout1[0]]/3600


    return
