# 前面的 docker build、push、sed 替换都不变...

# 5. 提交并推送到 Git 仓库 (触发 GitOps)
git add 05-agent.yaml
git commit -m "chore(deploy): update ops-agent image to $TAG"
git push origin main

# 6. ❌ 删掉之前的 kubectl apply，交给 ArgoCD 去做！
# echo "🔄 将配置应用到 K8s 集群..."  <-- 删掉
# kubectl apply -f 05-agent.yaml      <-- 删掉

echo "✅ 代码已推送至 Git 仓库，请稍候查看 ArgoCD 自动同步状态。"