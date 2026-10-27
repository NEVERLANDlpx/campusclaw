from app import create_app, load_local_env
load_local_env()
app=create_app()
if __name__=='__main__':
    app.run(host='127.0.0.1',port=8080,debug=False)
