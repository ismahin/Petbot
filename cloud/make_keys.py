"""Create local deployment secrets without writing them into Git history."""
from pathlib import Path
import secrets


def main():
    folder=Path(__file__).resolve().parent/'private'
    folder.mkdir(exist_ok=True)
    path=folder/'vercel.env'
    if path.exists():
        print('Existing cloud/private/vercel.env preserved. Open it locally to copy your deployment secrets.')
        return
    content='DESKTER_ADMIN_KEY='+secrets.token_urlsafe(40)+'\nDESKTER_DEVICE_KEY=dsk_'+secrets.token_urlsafe(32)+'\n'
    path.write_text(content,encoding='utf8')
    print('Created cloud/private/vercel.env. Secrets were not printed. Add them to Vercel environment variables.')


if __name__=='__main__':
    main()
