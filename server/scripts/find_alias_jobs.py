"""
Script to scan backend jobs and find one with alias candidates.
Saves the first matching job results JSON to frontend/job_<id>.json

Usage:
  python server/scripts/find_alias_jobs.py --limit 200 --save-dir ../frontend --relax

"""
import argparse
import json
import os
import sys
try:
    import requests
except Exception:
    requests = None
    from urllib import request as urllib_request


def fetch_json(url, headers=None):
    if requests:
        r = requests.get(url, headers=headers or {}, timeout=30)
        r.raise_for_status()
        return r.json()
    else:
        req = urllib_request.Request(url)
        if headers:
            for k, v in (headers or {}).items():
                req.add_header(k, v)
        with urllib_request.urlopen(req, timeout=30) as resp:
            return json.load(resp)


def post_json(url, payload, headers=None):
    if not requests:
        raise RuntimeError('POST requires requests package; install with: pip install requests')
    r = requests.post(url, json=payload, headers=headers or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def get_access_token(api_base, email, password):
    # Try login; if fails attempt register then login
    login_url = f"{api_base}/auth/login"
    register_url = f"{api_base}/auth/register"
    try:
        resp = post_json(login_url, {"email": email, "password": password})
        return resp.get('access_token')
    except Exception:
        # try register
        try:
            post_json(register_url, {"email": email, "password": password, "full_name": "cli"})
        except Exception:
            return None
        try:
            resp = post_json(login_url, {"email": email, "password": password})
            return resp.get('access_token')
        except Exception:
            return None


def check_line_for_alias(line, relax=False):
    ext = bool(line.get('ref_produit_facture') or line.get('ref_produit_bl'))
    intr = bool(line.get('ref_produit'))
    applied = line.get('reference_alias_applied')
    if applied is True or (isinstance(applied, str) and applied.lower() == 'true'):
        return False
    if not (ext and intr):
        return False

    if relax:
        return True

    # strict qty equality check when possible
    if line.get('ref_produit_facture'):
        if line.get('qty_bc') is not None and line.get('qty_facture') is not None:
            try:
                return int(line.get('qty_bc')) == int(line.get('qty_facture'))
            except Exception:
                return False
        return False
    else:
        if line.get('qty_bc') is not None and line.get('qty_bl') is not None:
            try:
                return int(line.get('qty_bc')) == int(line.get('qty_bl'))
            except Exception:
                return False
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--api', default='http://127.0.0.1:8000', help='Backend base URL')
    p.add_argument('--limit', type=int, default=200)
    p.add_argument('--email', help='User email for API auth', default=None)
    p.add_argument('--password', help='User password for API auth', default=None)
    p.add_argument('--save-dir', default='frontend', help='Directory to save matching job JSON')
    p.add_argument('--relax', action='store_true', help='Relax qty checks')
    args = p.parse_args()

    jobs_url = f"{args.api}/jobs?limit={args.limit}"
    headers = None
    if args.email and args.password:
        token = get_access_token(args.api, args.email, args.password)
        if token:
            headers = {"Authorization": f"Bearer {token}"}
    try:
        jobs = fetch_json(jobs_url, headers=headers)
    except Exception as e:
        print('ERROR: Unable to fetch jobs from', jobs_url, '->', e)
        sys.exit(2)

    os.makedirs(args.save_dir, exist_ok=True)

    for j in jobs:
        job_id = j.get('job_id') or j.get('id')
        if not job_id:
            continue
        res_url = f"{args.api}/jobs/{job_id}/results"
        try:
            res = fetch_json(res_url, headers=headers)
        except Exception:
            continue
        lvs = (res.get('match_result') or {}).get('line_verdicts')
        if not lvs:
            continue
        for line in lvs:
            if check_line_for_alias(line, relax=args.relax):
                out_path = os.path.join(args.save_dir, f"job_{job_id}.json")
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(res, f, ensure_ascii=False, indent=2)
                print('FOUND_JOB:' + str(job_id))
                print('SAVED_TO:' + out_path)
                sys.exit(0)

    print('NO_MATCH_FOUND')
    sys.exit(1)


if __name__ == '__main__':
    main()
